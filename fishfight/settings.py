"""Validated, fail-safe configuration for the Fish Fight macro."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .vision import VisionConfig

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "roi": None,
    "dry_run": True,
    "poll_hz": 90,
    "prediction_horizon_s": 0.45,
    "press_lead_s": 0.020,
    "green_h_min": 35,
    "green_h_max": 95,
    "green_s_min": 70,
    "green_v_min": 70,
    "white_s_max": 80,
    "white_v_min": 200,
    "zone_row_fraction": 0.20,
    "tick_row_fraction": 0.08,
}


def _is_json_number(value: object) -> bool:
    return type(value) in (int, float)


def _normalise_int(
    config: dict[str, Any],
    key: str,
    low: int,
    high: int,
    warnings: list[str],
) -> None:
    value = config.get(key)
    if type(value) is not int:
        config[key] = DEFAULT_CONFIG[key]
        warnings.append(f"{key} must be an integer; using {config[key]!r}")
        return
    bounded = min(high, max(low, value))
    if bounded != value:
        warnings.append(f"{key} was clamped to {bounded}")
    config[key] = bounded


def _normalise_float(
    config: dict[str, Any],
    key: str,
    low: float,
    high: float,
    warnings: list[str],
) -> None:
    raw = config.get(key)
    try:
        value = float(raw) if _is_json_number(raw) else math.nan
    except (OverflowError, TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value):
        config[key] = DEFAULT_CONFIG[key]
        warnings.append(f"{key} must be a finite number; using {config[key]!r}")
        return
    bounded = min(high, max(low, value))
    if bounded != value:
        warnings.append(f"{key} was clamped to {bounded}")
    config[key] = bounded


def normalize_config(loaded: object) -> tuple[dict[str, Any], list[str]]:
    """Merge defaults and reject malformed input configuration safely.

    A malformed dry_run value always falls back to True (no live input).
    A malformed saved ROI becomes None and requires a new calibration.
    """
    warnings: list[str] = []
    config = dict(DEFAULT_CONFIG)
    if isinstance(loaded, dict):
        config.update(loaded)
    else:
        warnings.append("configuration root must be a JSON object; using defaults")

    if type(config.get("dry_run")) is not bool:
        config["dry_run"] = True
        warnings.append("dry_run must be true or false; safely defaulting to true")

    roi = config.get("roi")
    if roi is not None:
        valid = isinstance(roi, dict)
        required = ("left", "top", "width", "height")
        if valid:
            valid = all(type(roi.get(key)) is int for key in required)
        if valid:
            left, top, width, height = (roi[key] for key in required)
            valid = (
                abs(left) <= 100_000
                and abs(top) <= 100_000
                and 12 <= width <= 16_384
                and 40 <= height <= 16_384
            )
        if not valid:
            config["roi"] = None
            warnings.append("ROI is malformed or outside safe size limits; recalibrate with F6")
        else:
            config["roi"] = {key: roi[key] for key in required}

    _normalise_int(config, "poll_hz", 20, 180, warnings)
    _normalise_float(config, "prediction_horizon_s", 0.05, 2.0, warnings)
    _normalise_float(config, "press_lead_s", 0.012, 0.045, warnings)

    for key in ("green_h_min", "green_h_max"):
        _normalise_int(config, key, 0, 179, warnings)
    for key in ("green_s_min", "green_v_min", "white_s_max", "white_v_min"):
        _normalise_int(config, key, 0, 255, warnings)
    for key in ("zone_row_fraction", "tick_row_fraction"):
        _normalise_float(config, key, 0.01, 1.0, warnings)

    if config["green_h_min"] > config["green_h_max"]:
        config["green_h_min"] = DEFAULT_CONFIG["green_h_min"]
        config["green_h_max"] = DEFAULT_CONFIG["green_h_max"]
        warnings.append("green_h_min exceeded green_h_max; restored default hue range")

    return config, warnings


def save_config(config: dict[str, Any], path: str | Path = CONFIG_PATH) -> None:
    """Write JSON atomically so an interrupted write cannot truncate config."""
    destination = Path(path)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    """Load, validate and safely repair a valid-but-malformed JSON config."""
    source = Path(path)
    if not source.exists():
        config = dict(DEFAULT_CONFIG)
        try:
            save_config(config, source)
        except OSError as exc:
            print(f"[config] couldn't create {source}: {exc}; using in-memory defaults")
        return config

    try:
        loaded = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[config] couldn't read {source}: {exc}; using safe in-memory defaults")
        return dict(DEFAULT_CONFIG)

    config, warnings = normalize_config(loaded)
    for warning in warnings:
        print(f"[config] {warning}")
    if warnings:
        try:
            save_config(config, source)
        except OSError as exc:
            print(f"[config] couldn't save repaired config: {exc}; using safe in-memory values")
    return config


def vision_config(config: dict[str, Any]) -> VisionConfig:
    keys = VisionConfig.__dataclass_fields__.keys()
    return VisionConfig(**{key: config[key] for key in keys if key in config})
