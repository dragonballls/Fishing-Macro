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


if __name__ == "__main__":
    unittest.main()
