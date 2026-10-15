"""Vision-LLM-assisted, review-before-save calibration for Fishing-Macro.

Cloud providers receive the Roblox client window and bundled calibration
references. The optional Ollama provider processes images on loopback. Captures
stay in memory; cloud API keys use the OS credential store.
"""
from __future__ import annotations
from copy import deepcopy
from collections.abc import Iterable, Mapping
import base64
import io
import json
import math
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODEL_NAME = "gemini-3.8-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL_NAME + ":generateContent"
KEY_SERVICE = "FishingMacro.GeminiAutoCalibration"
KEY_USER = "gemini-api-key"
LOCAL_PROVIDER = "Local LLM (Ollama)"
LOCAL_MODEL = "qwen2.5vl:3b"
LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1/chat/completions"
LOCAL_DOWNLOAD_URL = "https://ollama.com/download"
LOCAL_MODEL_URL = "https://ollama.com/library/qwen2.5vl"
MIN_CONFIDENCE = 0.88

# Every configured service below accepts image input at its documented endpoint.
# Users can override the model in the dialog; keys remain isolated per provider.
PROVIDER_CONFIGS = {
    "Gemini": {
        "kind": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/",
        "model": MODEL_NAME,
    },
    "OpenRouter": {
        "kind": "openai",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        # The free router selects an available model compatible with vision input.
        "model": "openrouter/free",
    },
    "Groq": {
        "kind": "openai",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "qwen/qwen3.8-27b",
    },
    "OpenAI": {
        "kind": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4.1-mini",
    },
    "Mistral": {
        "kind": "openai",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model": "ministral-14b-2512",
    },
    LOCAL_PROVIDER: {
        "kind": "openai",
        "endpoint": LOCAL_ENDPOINT,
        "model": LOCAL_MODEL,
        "local": True,
    },
}
PROVIDERS = tuple(PROVIDER_CONFIGS)

ALLOWED_KINDS = {
    "bar_search": "box", "zone_track": "box", "bite": "box", "meter": "box",
    "popup": "box", "learn": "box", "learn_click": "dot", "menu": "box",
    "center": "dot", "menu_item1": "dot", "menu_item2": "dot", "menu_item3": "dot",
    "menu_last": "dot", "craft_btn": "box", "craft_plus": "dot",
    "craft_button": "dot", "craft_close": "dot",
}
STATE_KEYS = {
    "normal_gameplay": set(),
    "reel_minigame": {"bar_search", "zone_track"},
    "bite_marker": {"bite"},
    "charge_meter": {"meter"},
    "catch_popup": {"popup"},
    "learn_popup": {"learn", "learn_click"},
    "npc_root_menu": {"menu", "menu_item1", "menu_item2", "menu_item3", "menu_last"},
    "npc_shop_menu": {"menu", "menu_item1", "menu_item2", "menu_last"},
    "npc_bait_menu": {"menu", "menu_item1", "menu_last"},
    "craft_window": {"craft_btn", "craft_plus", "craft_button", "craft_close"},
    "interact_prompt": {"center"},
    "unknown": set(),
}
REFERENCE_IMAGES = (
    ("Reel track", "calib/track.png"),
    ("Moving zone", "calib/zone.png"),
    ("Bite marker", "calib/bite.png"),
    ("Charge meter", "calib/meter.png"),
    ("Catch popup", "calib/popup.png"),
    ("Learn button", "calib/learn.png"),
    ("NPC top row", "calib/menu_item1.png"),
    ("NPC second row", "calib/menu_item2.png"),
    ("NPC third row", "calib/menu_item3.png"),
    ("NPC bottom row", "calib/menu_last.png"),
    ("Craft search area", "calib/craft_btn.png"),
    ("Add bait plus", "calib/craft_plus.png"),
    ("Craft confirm", "calib/craft_button.png"),
    ("Craft close", "calib/craft_close.png"),
    ("NPC interact prompt", "check_range.png"),
)


def capture_config_values(
    config: object,
    paths: Iterable[str],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot config fields once, preserving the earliest pre-preview value."""
    captured = deepcopy(dict(previous or {}))
    for path in paths:
        if not isinstance(path, str) or path.count(".") != 1:
            raise ValueError("Config snapshot paths must be 'section.field'.")
        section, field = path.split(".", 1)
        target = getattr(config, section, None)
        if target is None or not hasattr(target, field):
            raise ValueError(f"Unknown config field: {path}")
        captured.setdefault(path, deepcopy(getattr(target, field)))
    return captured


def restore_config_values(config: object, snapshot: Mapping[str, Any]) -> None:
    """Restore config values captured before an uncommitted AI preview."""
    for path, value in snapshot.items():
        if not isinstance(path, str) or path.count(".") != 1:
            raise ValueError("Config snapshot paths must be 'section.field'.")
        section, field = path.split(".", 1)
        target = getattr(config, section, None)
        if target is None or not hasattr(target, field):
            raise ValueError(f"Unknown config field: {path}")
        setattr(target, field, deepcopy(value))


class GeminiCalibrationError(RuntimeError):
    """Safe, user-displayable calibration/API failure."""


def is_quota_or_credit_error(error: BaseException) -> bool:
    """Whether a provider failure should trigger the no-credit local fallback."""
    message = str(error).casefold().replace("-", "_")
    return any(marker in message for marker in (
        "quota", "rate limit", "rate_limit", "insufficient credit",
        "out of credits", "billing limit", "resource_exhausted",
    ))


def _provider_key_location(provider: str = "Gemini") -> tuple[str, str]:
    """Return a provider-specific credential-store identity."""
    if provider not in PROVIDER_CONFIGS:
        raise GeminiCalibrationError("Choose a supported AI provider.")
    if provider == "Gemini":
        # Preserve the existing Gemini credential so current installations upgrade cleanly.
        return KEY_SERVICE, KEY_USER
    safe_name = "".join(ch for ch in provider if ch.isalnum())
    return f"FishingMacro.AICalibration.{safe_name}", "api-key"


def get_saved_api_key(provider: str = "Gemini") -> str | None:
    """Load a provider-specific API key from the OS credential store."""
    if provider == LOCAL_PROVIDER:
        return None
    service, username = _provider_key_location(provider)
    try:
        import keyring
        value = keyring.get_password(service, username)
        return value.strip() if isinstance(value, str) and value.strip() else None
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            "Windows Credential Manager is unavailable. Reinstall the app "
            "with its bundled dependencies, then try again."
        ) from exc


def save_api_key(api_key: str, provider: str = "Gemini") -> None:
    """Store the selected provider's non-empty key in the OS credential store."""
    if provider == LOCAL_PROVIDER:
        raise GeminiCalibrationError("The local Ollama provider does not use an API key.")
    api_key = api_key.strip()
    if not api_key or len(api_key) > 512 or any(ch.isspace() for ch in api_key):
        raise GeminiCalibrationError(f"Enter a valid {provider} API key.")
    service, username = _provider_key_location(provider)
    try:
        import keyring
        keyring.set_password(service, username, api_key)
        verified = keyring.get_password(service, username)
        if verified != api_key:
            raise GeminiCalibrationError(
                f"The {provider} key could not be verified in Windows Credential Manager."
            )
    except GeminiCalibrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            f"Could not store the {provider} key securely in Windows Credential Manager."
        ) from exc


def delete_saved_api_key(provider: str = "Gemini") -> None:
    if provider == LOCAL_PROVIDER:
        return
    service, username = _provider_key_location(provider)
    try:
        import keyring
        try:
            keyring.delete_password(service, username)
        except keyring.errors.PasswordDeleteError:
            pass
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            f"Could not remove the saved {provider} key from Windows Credential Manager."
        ) from exc


def frame_change_score(first_bgr, second_bgr) -> tuple[float, float]:
    """Cheap scene-change score for monitoring; never makes an API call itself."""
    try:
        import cv2
        import numpy as np
        def thumbnail(frame):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        a = thumbnail(first_bgr)
        b = thumbnail(second_bgr)
        diff = np.abs(a.astype("int16") - b.astype("int16"))
        return float(diff.mean()), float((diff >= 30).mean())
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError("Could not compare game screenshots.") from exc


def screen_changed(first_bgr, second_bgr) -> bool:
    """Ignore tiny animation noise while noticing menu/minigame transitions."""
    mean_diff, changed_fraction = frame_change_score(first_bgr, second_bgr)
    return (mean_diff >= 9.0 and changed_fraction >= 0.025) or changed_fraction >= 0.09


def _image_bytes(frame_bgr, max_edge: int = 1600) -> bytes:
    try:
        from PIL import Image
        image = Image.fromarray(frame_bgr[:, :, ::-1])
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=84, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError("Could not prepare the game screenshot.") from exc


def _reference_sheet(asset_root: Path) -> bytes | None:
    """Compose repository reference PNGs into one labeled, compact image."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        entries = []
        for label, relative in REFERENCE_IMAGES:
            path = asset_root / relative
            if not path.is_file():
                continue
            try:
                with Image.open(path) as source:
                    thumb = source.convert("RGB")
                    thumb.thumbnail((204, 116), Image.Resampling.LANCZOS)
                    entries.append((label, thumb.copy()))
            except (OSError, ValueError):
                continue
        if not entries:
            return None
        columns, cell_w, cell_h = 3, 220, 150
        rows = math.ceil(len(entries) / columns)
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#111827")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except OSError:
            font = ImageFont.load_default()
        for i, (label, thumb) in enumerate(entries):
            x, y = (i % columns) * cell_w, (i // columns) * cell_h
            draw.text((x + 8, y + 5), label, fill="#f9fafb", font=font)
            px = x + (cell_w - thumb.width) // 2
            py = y + 28 + max(0, (116 - thumb.height) // 2)
            sheet.paste(thumb, (px, py))
        out = io.BytesIO()
        sheet.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError("Could not load the bundled reference images.") from exc


def _proposal_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "screen_state": {"type": "STRING", "enum": list(STATE_KEYS)},
            "summary": {"type": "STRING"},
            "next_instruction": {"type": "STRING"},
            "regions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "key": {"type": "STRING", "enum": list(ALLOWED_KINDS)},
                        "kind": {"type": "STRING", "enum": ["box", "dot"]},
                        "coords": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                        "confidence": {"type": "NUMBER"},
                        "evidence": {"type": "STRING"},
                    },
                    "required": ["key", "kind", "coords", "confidence", "evidence"],
                },
            },
        },
        "required": ["screen_state", "summary", "next_instruction", "regions"],
    }


def _clean_text(value: Any, default: str, max_len: int = 300) -> str:
    if not isinstance(value, str):
        return default
    value = " ".join(value.replace("\x00", "").split())
    return value[:max_len] or default


def validate_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Whitelist model output and accept only high-confidence, visible targets."""
    state = raw.get("screen_state")
    if state not in STATE_KEYS:
        state = "unknown"
    summary = _clean_text(raw.get("summary"), "The AI model inspected the current game screen.")
    next_instruction = _clean_text(
        raw.get("next_instruction"),
        "Keep Roblox visible and capture the next screen when the relevant UI appears.",
    )
    accepted = []
    seen: set[str] = set()
    items = raw.get("regions")
    if not isinstance(items, list):
        items = []
    permitted = STATE_KEYS[state]
    for item in items:
        if not isinstance(item, dict):
            continue
        key, kind = item.get("key"), item.get("kind")
        if key not in ALLOWED_KINDS or key not in permitted or key in seen:
            continue
        if kind != ALLOWED_KINDS[key]:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
            coords = [float(v) for v in item.get("coords", [])]
        except (TypeError, ValueError):
            continue
        needed = 4 if kind == "box" else 2
        if len(coords) != needed or not all(math.isfinite(v) for v in coords):
            continue
        if not all(0.0 <= v <= 1000.0 for v in coords):
            continue
        if confidence < MIN_CONFIDENCE or confidence > 1.0:
            continue
        if kind == "box":
            left, top, right, bottom = coords
            if right <= left or bottom <= top:
                continue
            width, height = right - left, bottom - top
            min_box = {
                "bar_search": (220, 55), "zone_track": (180, 35),
                "bite": (70, 65), "meter": (430, 240),
                "popup": (100, 90), "learn": (55, 30),
                "menu": (80, 120), "craft_btn": (60, 30),
            }.get(key, (30, 20))
            if width < min_box[0] or height < min_box[1]:
                continue
            if key == "meter" and (left < 30 or right > 970):
                continue
        seen.add(key)
        accepted.append({
            "key": key, "kind": kind,
            "coords": [v / 1000.0 for v in coords],
            "confidence": confidence,
            "evidence": _clean_text(item.get("evidence"), "Target visibly matched.", 180),
        })
    return {
        "screen_state": state, "summary": summary,
        "next_instruction": next_instruction, "proposals": accepted,
    }


def analyze_screenshot(
    frame_bgr, api_key: str, asset_root: str | Path,
    timeout: float = 35.0, provider: str = "Gemini", model: str | None = None,
) -> dict[str, Any]:
    """Analyze one live game-window frame using a selected vision API."""
    api_key = (api_key or "").strip()
    if provider != LOCAL_PROVIDER and not api_key:
        raise GeminiCalibrationError(f"No {provider} API key was provided.")
    config = PROVIDER_CONFIGS.get(provider)
    if config is None:
        raise GeminiCalibrationError("Choose a supported AI provider.")
    model = (model or "").strip() or config["model"]
    allowed_model_chars = "._/-" + (":" if provider == LOCAL_PROVIDER else "")
    if (len(model) > 120 or not model
            or not all(ch.isalnum() or ch in allowed_model_chars for ch in model)
            or ".." in model or model.startswith("/") or model.endswith("/")):
        raise GeminiCalibrationError("The model name contains unsupported characters.")

    screenshot = _image_bytes(frame_bgr)
    reference = _reference_sheet(Path(asset_root))
    expected_keys = ", ".join(ALLOWED_KINDS)
    prompt = f"""
You are calibrating the Fishing-Macro Windows app for the Blox Fruits fishing minigame.
The FIRST image is a screenshot of only the Roblox client window. The SECOND image
is a labeled sheet of bundled reference pictures from the app. Match reference
pictures to the actual game UI; do not treat reference-sheet items as visible in-game.

Return ONLY a single JSON object with exactly these top-level fields:
screen_state (string), summary (string), next_instruction (string), regions (array).
Each regions item must have key, kind, coords, confidence, evidence. No Markdown fences.
Normalize screen coordinates to 0..1000, origin top-left. A box uses [left, top, right,
bottom]; a dot uses [x, y]. Coordinates are later converted into game-window fractions.

Allowed calibration keys and types: {expected_keys}
bar_search: tight around the full reel track plus progress strip; exclude health/energy and mastery HUD.
zone_track: tight optional box around the inner moving track and progress strip.
bite: around the pink ! marker, excluding the top-right player list.
meter: broad central search band for the moving green charge meter; never a tiny box around one frame.
popup: fallback area around the catch card.
learn and learn_click: search area and centre of visible blue Learn button.
menu: encompass currently visible dialogue rows, not chat/player list.
center: centre of a visible Interact prompt.
menu_item1/2/3/menu_last: centres of corresponding rows visible in this screenshot only.
craft_btn: around yellow Craft detection area.
craft_plus/craft_button/craft_close: centres of visible plus, Craft, and Close buttons.

Choose one screen_state: normal_gameplay, reel_minigame, bite_marker, charge_meter,
catch_popup, learn_popup, npc_root_menu, npc_shop_menu, npc_bait_menu, craft_window,
interact_prompt, unknown. Only emit targets visibly present and unambiguous in the LIVE
screenshot. Never guess locations of hidden controls. Confidence must reflect visual evidence.
If unclear, emit no region and give one actionable next_instruction explaining what UI to show.
Do not ask the user to upload/save screenshots; this app captures them automatically.
All suggested changes are reviewed in the app before saving.
"""
    try:
        if config["kind"] == "gemini":
            parts = [
                {"text": prompt},
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(screenshot).decode("ascii"),
                }},
            ]
            if reference:
                parts.append({"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(reference).decode("ascii"),
                }})
            body = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": _proposal_schema(),
                    "maxOutputTokens": 1800,
                },
            }
            request = urllib.request.Request(
                config["endpoint"] + model + ":generateContent",
                data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                method="POST",
            )
        else:
            def image_part(image_bytes: bytes) -> dict[str, Any]:
                encoded = base64.b64encode(image_bytes).decode("ascii")
                return {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + encoded, "detail": "high"},
                }

            content = [{"type": "text", "text": prompt}, image_part(screenshot)]
            if reference:
                content.append(image_part(reference))
            body = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
                "max_tokens": 2200,
                "temperature": 0,
            }
            headers = {"Content-Type": "application/json"}
            if provider != LOCAL_PROVIDER:
                headers["Authorization"] = "Bearer " + api_key
            if provider == "OpenRouter":
                headers["HTTP-Referer"] = "https://github.com/dragonballls/Fishing-Macro"
                headers["X-Title"] = "Fishing Macro"
            request = urllib.request.Request(
                config["endpoint"],
                data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                headers=headers,
                method="POST",
            )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if provider == LOCAL_PROVIDER and exc.code == 404:
            raise GeminiCalibrationError(
                f"Ollama could not find the local vision model '{model}'. "
                f"Install it from {LOCAL_MODEL_URL}, then run: ollama pull {model}"
            ) from exc
        if provider == LOCAL_PROVIDER and exc.code in (400, 500):
            raise GeminiCalibrationError(
                f"Ollama rejected the local vision request. Confirm '{model}' is installed "
                "and supports image input; if needed, run its ollama pull command again."
            ) from exc
        if exc.code in (401, 403):
            raise GeminiCalibrationError(
                f"{provider} rejected the API key or account permission. Check the key and provider dashboard."
            ) from exc
        if exc.code == 429:
            raise GeminiCalibrationError(
                f"{provider} rate limit or quota is exhausted. Switch providers or check the provider dashboard."
            ) from exc
        if exc.code == 402:
            raise GeminiCalibrationError(
                f"{provider} reports insufficient credits. Check the account balance or select another provider."
            ) from exc
        if exc.code == 400:
            raise GeminiCalibrationError(
                f"{provider} rejected the model or request. Confirm the model supports vision and JSON output."
            ) from exc
        raise GeminiCalibrationError(f"{provider} API returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        if provider == LOCAL_PROVIDER:
            raise GeminiCalibrationError(
                "Could not connect to Ollama at 127.0.0.1:11434. Install/start Ollama, "
                f"then run: ollama pull {model}. The model is downloaded separately and "
                "local inference can use substantial RAM/VRAM."
            ) from exc
        raise GeminiCalibrationError(
            f"Could not reach {provider}. Check your internet connection and selected model, then retry."
        ) from exc
    except TimeoutError as exc:
        if provider == LOCAL_PROVIDER:
            raise GeminiCalibrationError(
                "The local vision model timed out. Retry when the PC is less busy or use a cloud provider."
            ) from exc
        raise GeminiCalibrationError(f"{provider} timed out; retry the current calibration step.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GeminiCalibrationError(f"{provider} returned an unreadable response; retry the step.") from exc

    try:
        if config["kind"] == "gemini":
            candidates = payload.get("candidates") or []
            parts_out = candidates[0]["content"]["parts"]
            response_text = "\n".join(
                part.get("text", "") for part in parts_out if isinstance(part, dict)
            ).strip()
        else:
            choices = payload.get("choices") or []
            message = choices[0]["message"]
            content_out = message.get("content", "")
            if isinstance(content_out, str):
                response_text = content_out.strip()
            elif isinstance(content_out, list):
                response_text = "\n".join(
                    item.get("text", "") for item in content_out
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ).strip()
            else:
                response_text = ""
        fence = chr(96) * 3
        if response_text.startswith(fence):
            response_text = response_text.split("\n", 1)[1].rsplit(fence, 1)[0].strip()
        raw = json.loads(response_text)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise GeminiCalibrationError(
            f"{provider} did not return valid calibration JSON. Retry with the relevant game UI visible."
        ) from exc
    if not isinstance(raw, dict):
        raise GeminiCalibrationError(f"{provider} returned an invalid calibration response.")
    return validate_response(raw)

