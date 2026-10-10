"""Prediction utilities for the moving tick and green target zone."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque

from .vision import GaugeReading


@dataclass(frozen=True)
class Sample:
    timestamp: float
    tick_y: float
    zone_center: float


class MotionHistory:
    def __init__(self, maxlen: int = 8) -> None:
        self.samples: Deque[Sample] = deque(maxlen=maxlen)

    def clear(self) -> None:
        self.samples.clear()

    def add(self, timestamp: float, reading: GaugeReading) -> None:
        self.samples.append(Sample(timestamp, reading.tick_y, reading.zone_center))

    def _slope(self, field: str) -> float | None:
        if len(self.samples) < 3:
            return None
        ts = [getattr(s, "timestamp") for s in self.samples]
        ys = [getattr(s, field) for s in self.samples]
        if any(not math.isfinite(value) for value in (*ts, *ys)):
            return None
        if any(later <= earlier for earlier, later in zip(ts, ts[1:])):
            return None
        t0 = ts[0]
        xs = [t - t0 for t in ts]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator < 1e-8:
            return None
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
        if abs(slope) > 8.0:
            return None
        return slope

    def velocities(self) -> tuple[float, float] | None:
        tick_v = self._slope("tick_y")
        zone_v = self._slope("zone_center")
        if tick_v is None or zone_v is None:
            return None
        return tick_v, zone_v


def reflect(position: float, low: float, high: float) -> float:
    """Reflect a linear prediction at a bouncing gauge boundary."""
    span = high - low
    if span <= 0:
        raise ValueError("high must be greater than low")
    offset = (position - low) % (2.0 * span)
    return low + offset if offset <= span else high - (offset - span)


def time_to_alignment(
    reading: GaugeReading,
    history: MotionHistory,
    *,
    horizon_s: float = 0.45,
    step_s: float = 0.0025,
    safe_zone_fraction: float = 0.62,
) -> float | None:
    """Estimate time until the tick enters the central portion of the green zone.

    Positions are normalized to the full calibrated track. Both features are
    predicted within the track bounds; do not fold a valid green-zone reading
    from the lower/upper part of the track into an invented central position.
    """
    values = (
        reading.tick_y, reading.zone_top, reading.zone_bottom,
        horizon_s, step_s, safe_zone_fraction,
    )
    if any(not math.isfinite(value) for value in values):
        return None
    if not (0.02 <= reading.tick_y <= 0.98):
        return None
    if not (0.02 <= reading.zone_top < reading.zone_bottom <= 0.98):
        return None
    if horizon_s <= 0 or step_s <= 0:
        return None
    if not (0 < safe_zone_fraction <= 1):
        return None

    velocity = history.velocities()
    if velocity is None:
        return None
    tick_v, zone_v = velocity
    zone_half = reading.zone_half_height
    if zone_half <= 0:
        return None
    tolerance = max(0.002, zone_half * safe_zone_fraction)
    count = int(horizon_s / step_s) + 1
    for i in range(count):
        dt = i * step_s
        predicted_tick = reflect(reading.tick_y + tick_v * dt, 0.02, 0.98)
        predicted_zone = reflect(reading.zone_center + zone_v * dt, 0.02, 0.98)
        if abs(predicted_tick - predicted_zone) <= tolerance:
            return dt
    return None
