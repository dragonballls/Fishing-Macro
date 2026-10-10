"""Pixel-based detection for the Sharkman Master Fish Fight gauge.

This intentionally only reads the visible screen. It does not inspect process
memory, inject code into Roblox, or call game remotes.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class GaugeReading:
    """Normalized positions detected inside the calibrated gauge rectangle."""

    tick_y: float
    zone_top: float
    zone_bottom: float
    tick_strength: float
    zone_strength: float

    @property
    def zone_center(self) -> float:
        return (self.zone_top + self.zone_bottom) / 2.0

    @property
    def zone_half_height(self) -> float:
        return max(0.0, (self.zone_bottom - self.zone_top) / 2.0)


@dataclass(frozen=True)
class VisionConfig:
    green_h_min: int = 35
    green_h_max: int = 95
    green_s_min: int = 70
    green_v_min: int = 70
    white_s_max: int = 80
    white_v_min: int = 200
    zone_row_fraction: float = 0.20
    tick_row_fraction: float = 0.08
    min_zone_height_fraction: float = 0.004
    max_zone_height_fraction: float = 0.25
    max_tick_height_fraction: float = 0.08


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return half-open runs of True values in a one-dimensional mask."""
    values = np.asarray(mask, dtype=np.bool_)
    padded = np.concatenate(([False], values, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends)]


def detect_gauge(frame_bgr: np.ndarray, config: VisionConfig | None = None) -> GaugeReading | None:
    """Detect the green target band and white moving tick in a tight gauge crop.

    frame_bgr should contain just the meter track and a small margin. Cropping
    out other UI is important so green health bars and white text do not count.
    Positions returned are fractions of crop height, in [0, 1].
    """
    cfg = config or VisionConfig()
    if (not isinstance(frame_bgr, np.ndarray) or frame_bgr.ndim != 3
            or frame_bgr.shape[2] < 3):
        return None
    h, w = frame_bgr.shape[:2]
    if h < 40 or w < 12:
        return None

    bgr = np.ascontiguousarray(frame_bgr[:, :, :3])
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h_channel, s_channel, v_channel = cv2.split(hsv)

    green = (
        (h_channel >= cfg.green_h_min)
        & (h_channel <= cfg.green_h_max)
        & (s_channel >= cfg.green_s_min)
        & (v_channel >= cfg.green_v_min)
    )
    green_fraction = green.mean(axis=1)
    green_cutoff = max(0.12, cfg.zone_row_fraction)
    zone_rows = green_fraction >= green_cutoff
    min_zone_px = max(2, int(h * cfg.min_zone_height_fraction))
    max_zone_px = max(min_zone_px, int(h * cfg.max_zone_height_fraction))
    zone_candidates = []
    for start, end in _runs(zone_rows):
        size = end - start
        if min_zone_px <= size <= max_zone_px:
            strength = float(green_fraction[start:end].mean())
            score = strength * (size ** 0.5)
            zone_candidates.append((score, start, end, strength))
    if not zone_candidates:
        return None
    _, zone_start, zone_end, zone_strength = max(zone_candidates)

    white = (s_channel <= cfg.white_s_max) & (v_channel >= cfg.white_v_min)
    white_fraction = white.mean(axis=1)
    white_cutoff = max(0.04, cfg.tick_row_fraction)
    tick_rows = white_fraction >= white_cutoff
    max_tick_px = max(4, int(h * cfg.max_tick_height_fraction))
    tick_candidates = []
    for start, end in _runs(tick_rows):
        size = end - start
        if 1 <= size <= max_tick_px:
            strength = float(white_fraction[start:end].max())
            if strength >= white_cutoff:
                tick_candidates.append((strength, start, end))
    if not tick_candidates:
        return None

    tick_strength, tick_start, tick_end = max(tick_candidates, key=lambda item: item[0])
    tick_mid = (tick_start + tick_end - 1) / 2.0
    zone_top = zone_start / float(h)
    zone_bottom = zone_end / float(h)
    tick_y = tick_mid / float(h)

    if not (0.005 <= tick_y <= 0.995):
        return None
    return GaugeReading(
        tick_y=float(np.clip(tick_y, 0.0, 1.0)),
        zone_top=float(zone_top),
        zone_bottom=float(zone_bottom),
        tick_strength=tick_strength,
        zone_strength=zone_strength,
    )


def draw_diagnostics(frame_bgr: np.ndarray, reading: GaugeReading | None) -> np.ndarray:
    """Return a diagnostic copy with detected lines drawn over the crop."""
    out = frame_bgr[:, :, :3].copy()
    h, w = out.shape[:2]
    if reading is None:
        cv2.putText(out, "Gauge not detected", (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 255), 2, cv2.LINE_AA)
        return out
    y_top = int(reading.zone_top * h)
    y_bottom = max(y_top + 1, int(reading.zone_bottom * h))
    y_tick = int(reading.tick_y * h)
    cv2.rectangle(out, (0, y_top), (w - 1, y_bottom), (0, 255, 0), 2)
    cv2.line(out, (0, y_tick), (w - 1, y_tick), (255, 255, 255), 2)
    delta = reading.tick_y - reading.zone_center
    cv2.putText(out, f"tick={reading.tick_y:.3f} zone={reading.zone_center:.3f} d={delta:+.3f}",
                (5, max(20, min(h - 5, y_tick - 8))), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (255, 255, 0), 1, cv2.LINE_AA)
    return out
