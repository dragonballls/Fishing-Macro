import unittest

import numpy as np

from fishfight.vision import VisionConfig, detect_gauge


class VisionTests(unittest.TestCase):
    def sample_gauge(self, with_tick=True):
        image = np.full((200, 60, 3), (30, 30, 30), dtype=np.uint8)
        image[90:106, 3:57] = (25, 220, 35)  # BGR target band
        if with_tick:
            image[50:53, 20:40] = (245, 245, 245)
        return image

    def test_detects_zone_and_tick(self):
        reading = detect_gauge(self.sample_gauge())
        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertAlmostEqual(reading.tick_y, 51 / 200, delta=0.01)
        self.assertAlmostEqual(reading.zone_center, 98 / 200, delta=0.02)
        self.assertGreater(reading.tick_strength, 0.2)
        self.assertGreater(reading.zone_strength, 0.7)

    def test_rejects_zone_without_tick(self):
        self.assertIsNone(detect_gauge(self.sample_gauge(with_tick=False)))

    def test_rejects_unrelated_dark_crop(self):
        image = np.full((200, 60, 3), (30, 30, 30), dtype=np.uint8)
        self.assertIsNone(detect_gauge(image))

    def test_rejects_too_small_crop(self):
        image = np.zeros((20, 10, 3), dtype=np.uint8)
        self.assertIsNone(detect_gauge(image))

    def test_hue_thresholds_can_be_overridden(self):
        image = self.sample_gauge()
        config = VisionConfig(green_h_min=45, green_h_max=95)
        self.assertIsNotNone(detect_gauge(image, config))


if __name__ == "__main__":
    unittest.main()
