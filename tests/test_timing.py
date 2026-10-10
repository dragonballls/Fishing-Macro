import unittest

from fishfight.timing import MotionHistory, reflect, time_to_alignment
from fishfight.vision import GaugeReading


class TimingTests(unittest.TestCase):
    def test_reflects_at_both_boundaries(self):
        self.assertAlmostEqual(reflect(1.1, 0.0, 1.0), 0.9)
        self.assertAlmostEqual(reflect(-0.1, 0.0, 1.0), 0.1)
        self.assertAlmostEqual(reflect(0.5, 0.0, 1.0), 0.5)

    def test_waits_for_motion_history(self):
        reading = GaugeReading(0.30, 0.44, 0.50, 0.4, 0.8)
        history = MotionHistory()
        history.add(1.0, reading)
        self.assertIsNone(time_to_alignment(reading, history))

    def test_stationary_aligned_feature_is_not_a_trigger(self):
        history = MotionHistory()
        reading = GaugeReading(0.50, 0.48, 0.52, 0.8, 0.9)
        for index in range(6):
            history.add(index * 0.02, reading)
        self.assertIsNone(time_to_alignment(reading, history))

    def test_predicts_entry_into_target_zone(self):
        history = MotionHistory()
        for i in range(5):
            history.add(i * 0.02, GaugeReading(0.30 + i * 0.02, 0.445, 0.495, 0.5, 0.9))
        current = GaugeReading(0.38, 0.445, 0.495, 0.5, 0.9)
        eta = time_to_alignment(current, history, horizon_s=0.3)
        self.assertIsNotNone(eta)
        assert eta is not None
        self.assertGreaterEqual(eta, 0)
        self.assertLessEqual(eta, 0.10)

    def test_returns_none_when_target_is_outside_horizon(self):
        history = MotionHistory()
        for i in range(5):
            history.add(i * 0.02, GaugeReading(0.15 + i * 0.002, 0.445, 0.495, 0.5, 0.9))
        current = GaugeReading(0.16, 0.445, 0.495, 0.5, 0.9)
        self.assertIsNone(time_to_alignment(current, history, horizon_s=0.08))


    def test_does_not_fold_low_green_zone_into_central_track(self):
        history = MotionHistory()
        # A descending white tick and a green zone near the lower part of the
        # bar must not be reflected from 0.184 to a fictional position near 0.584.
        samples = [
            (0.00, 0.627, 0.188),
            (0.02, 0.624, 0.187),
            (0.04, 0.621, 0.186),
            (0.06, 0.618, 0.185),
            (0.08, 0.615, 0.184),
        ]
        for timestamp, tick, zone in samples:
            history.add(timestamp, GaugeReading(tick, zone - 0.02, zone + 0.02, 0.8, 0.9))
        current = GaugeReading(0.615, 0.164, 0.204, 0.8, 0.9)
        self.assertIsNone(time_to_alignment(current, history, horizon_s=0.30))

    def test_rejects_invalid_or_non_finite_readings(self):
        history = MotionHistory()
        for i in range(4):
            history.add(i * 0.02, GaugeReading(0.30 + i * 0.01, 0.44, 0.50, 0.5, 0.9))
        invalid = GaugeReading(0.35, 0.95, 1.01, 0.5, 0.9)
        self.assertIsNone(time_to_alignment(invalid, history))
        non_finite = GaugeReading(float("nan"), 0.44, 0.50, 0.5, 0.9)
        self.assertIsNone(time_to_alignment(non_finite, history))

    def test_rejects_non_monotonic_history_timestamps(self):
        history = MotionHistory()
        history.add(1.0, GaugeReading(0.3, 0.44, 0.50, 0.5, 0.9))
        history.add(0.9, GaugeReading(0.4, 0.44, 0.50, 0.5, 0.9))
        history.add(0.8, GaugeReading(0.5, 0.44, 0.50, 0.5, 0.9))
        self.assertIsNone(time_to_alignment(GaugeReading(0.5, 0.44, 0.50, 0.5, 0.9), history))

    def test_resets_motion_history_after_a_direction_reversal(self):
        history = MotionHistory()
        points = [0.94, 0.96, 0.98, 0.96, 0.94, 0.92]
        for index, tick in enumerate(points):
            history.add(index * 0.02, GaugeReading(tick, 0.48, 0.52, 0.8, 0.9))
        velocity = history.velocities()
        self.assertIsNotNone(velocity)
        assert velocity is not None
        self.assertLess(velocity[0], 0.0)


if __name__ == "__main__":
    unittest.main()
