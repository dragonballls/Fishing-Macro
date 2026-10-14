"""Gemini-assisted, review-before-save calibration for Fishing-Macro.

Only the Roblox client window and bundled calibration references are sent to
Gemini. Captures are processed in memory; API keys use the OS credential store
and are never written to config.json or logged.
"""
from __future__ import annotations
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
MIN_CONFIDENCE = 0.78

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


class GeminiCalibrationError(RuntimeError):
    """Safe, user-displayable calibration/API failure."""


def get_saved_api_key() -> str | None:
    """Load the Gemini key from the OS credential store; never from a file."""
    try:
        import keyring
        value = keyring.get_password(KEY_SERVICE, KEY_USER)
        return value.strip() if isinstance(value, str) and value.strip() else None
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            "Windows Credential Manager is unavailable. Reinstall the app "
            "with its bundled dependencies, then try again."
        ) from exc


def save_api_key(api_key: str) -> None:
    """Store a non-empty key using the active OS credential-store backend."""
    api_key = api_key.strip()
    if not api_key or len(api_key) > 512 or any(ch.isspace() for ch in api_key):
        raise GeminiCalibrationError("Enter a valid Gemini API key.")
    try:
        import keyring
        keyring.set_password(KEY_SERVICE, KEY_USER, api_key)
        verified = keyring.get_password(KEY_SERVICE, KEY_USER)
        if verified != api_key:
            raise GeminiCalibrationError(
                "The key could not be verified in Windows Credential Manager."
            )
    except GeminiCalibrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            "Could not store the key securely in Windows Credential Manager."
        ) from exc


def delete_saved_api_key() -> None:
    try:
        import keyring
        try:
            keyring.delete_password(KEY_SERVICE, KEY_USER)
        except keyring.errors.PasswordDeleteError:
            pass
    except Exception as exc:  # noqa: BLE001
        raise GeminiCalibrationError(
            "Could not remove the saved Gemini key from Windows Credential Manager."
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
    summary = _clean_text(raw.get("summary"), "Gemini inspected the current game screen.")
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


def analyze_screenshot(frame_bgr, api_key: str, asset_root: str | Path,
                       timeout: float = 35.0) -> dict[str, Any]:
    """Send one live game-window frame and the reference contact sheet to Gemini."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise GeminiCalibrationError("No Gemini API key was provided.")
    screenshot = _image_bytes(frame_bgr)
    reference = _reference_sheet(Path(asset_root))
    expected_keys = ", ".join(ALLOWED_KINDS)
    prompt = f"""
You are calibrating the Fishing-Macro Windows app for the Blox Fruits fishing minigame.
The FIRST image is a screenshot of only the Roblox client window. The SECOND image
is a labeled sheet of bundled reference pictures from the app. Match reference
pictures to the actual game UI; do not treat reference-sheet items as visible in-game.

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
    parts = [
        {"text": prompt},
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(screenshot).decode("ascii")}},
    ]
    if reference:
        parts.append({"inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(reference).decode("ascii"),
        }})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": _proposal_schema(),
            "maxOutputTokens": 1800,
        },
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_data = json.loads(exc.read().decode("utf-8"))
            detail = error_data.get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        if exc.code in (400, 401, 403):
            raise GeminiCalibrationError(
                "Gemini rejected the API key or request. Recheck the key and that "
                "the Gemini API is enabled for its Google project."
            ) from exc
        if exc.code == 429:
            raise GeminiCalibrationError(
                "Gemini rate limit or quota reached. Check the project's API quota and retry later."
            ) from exc
        raise GeminiCalibrationError(f"Gemini API returned HTTP {exc.code}. {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiCalibrationError(
            "Could not reach the Gemini API. Check your internet connection and try again."
        ) from exc
    except TimeoutError as exc:
        raise GeminiCalibrationError("Gemini timed out; retry the current calibration step.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GeminiCalibrationError("Gemini returned an unreadable response; retry the step.") from exc

    try:
        candidates = payload.get("candidates") or []
        parts_out = candidates[0]["content"]["parts"]
        response_text = "\n".join(
            part.get("text", "") for part in parts_out if isinstance(part, dict)
        ).strip()
        fence = chr(96) * 3
        if response_text.startswith(fence):
            response_text = response_text.split("\n", 1)[1].rsplit(fence, 1)[0].strip()
        raw = json.loads(response_text)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        api_error = payload.get("error", {}).get("message", "")
        raise GeminiCalibrationError(
            "Gemini did not return valid calibration JSON. "
            + (str(api_error)[:180] if api_error else "Retry with the relevant game UI visible.")
        ) from exc
    return validate_response(raw)
