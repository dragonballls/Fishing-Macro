"""Issue #38: translucent root rows must remain detectable and settle safely."""
from types import SimpleNamespace
import unittest
from unittest import mock

import cv2
import numpy as np

from bloxfish import shop, vision
from bloxfish.config import Config
from bloxfish.capture import Rect


class NPCMenuDetectionTests(unittest.TestCase):
    def test_opposite_sides_of_the_search_area_are_not_a_stack(self):
        self.assertEqual(shop._coherent_menu_stack([(193, 15), (478, 129)],
                         Rect(0, 0, 525, 345)), [])

    def test_four_labels_recover_root_when_dark_backdrop_merges_last_panels(self):
        image = np.full((350, 420, 3), 240, dtype=np.uint8)
        for top, bottom in ((30, 95), (110, 175), (190, 340)):
            image[top:bottom, 15:330] = 30
        for text, baseline in zip(('Shop', 'Fishing Index', 'Job Stats', 'Nevermind'),
                                  (73, 153, 233, 313)):
            cv2.putText(image, text, (60, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                        .9, (255, 255, 255), 2, cv2.LINE_AA)
        # Sky/water remains bright beside the fading panels.
        self.assertEqual(len(vision._find_menu_panels(image)), 2)
        rows = vision.find_falling_menu_buttons(image)
        self.assertEqual(len(rows), 4)
        for row, y in zip(rows, (63, 143, 223, 303)):
            self.assertLess(abs(row.y - y), 5)
            self.assertTrue(15 < row.x < 330)

    def test_bright_water_and_cursor_without_panels_do_not_form_a_menu(self):
        image = np.full((350, 420, 3), (235, 180, 100), dtype=np.uint8)
        for y in (45, 125, 205, 285):
            image[y:y + 16, 40:320] = 255
        self.assertEqual(vision.find_falling_menu_buttons(image), [])

    def test_pointer_extension_does_not_hide_nevermind(self):
        image = np.full((345, 525, 3), 210, dtype=np.uint8)
        # A continuous dark backing means the panel-only scan has no stack.
        image[25:330, 15:400] = 30
        for y in (40, 120, 200, 280):
            image[y:y + 22, 60:270] = 255
        image[301:336, 240:250] = 255  # pointer touching the final white label
        self.assertEqual(len(vision.find_falling_menu_buttons(image)), 4)

    def test_signature_tolerates_only_small_nonaccumulating_jitter(self):
        base = ((100, 100), (160, 180), (130, 260), (145, 340))
        jitter = tuple((x + 6, y + 2) for x, y in base)
        self.assertTrue(shop._same_menu_page_signature(base, jitter))
        self.assertFalse(shop._same_menu_page_signature(base, base[:3]))
        self.assertFalse(shop._same_menu_page_signature(base, ('legacy', 4)))
        self.assertFalse(shop._same_menu_page_signature(base,
                         tuple((x, y + 5) for x, y in base)))
        self.assertFalse(shop._same_menu_page_signature(base,
                         tuple((x + 12, y) for x, y in base)))

    def run_page_wait(self, signature_at):
        clock = [0.0]
        engine = SimpleNamespace(cfg=Config(), _alive=lambda: True)
        def sleep(seconds):
            clock[0] += seconds
        with mock.patch.object(shop, '_menu_page_signature',
                               side_effect=lambda _engine: signature_at(clock[0])), \
                mock.patch.object(shop.time, 'perf_counter', side_effect=lambda: clock[0]), \
                mock.patch.object(shop.time, 'sleep', side_effect=sleep):
            result = shop.wait_for_menu_page(engine, 'root', 1.2)
        return result, clock[0]

    def test_complete_page_with_compression_jitter_can_settle(self):
        base = ((100, 100), (160, 180), (130, 260), (145, 340))
        result, elapsed = self.run_page_wait(lambda t:
            tuple((x + (int(t * 100) % 2) * 6, y) for x, y in base))
        self.assertTrue(result)
        self.assertGreaterEqual(elapsed, .65)

    def test_partial_or_continuously_falling_page_cannot_settle(self):
        base = ((100, 100), (160, 180), (130, 260), (145, 340))
        self.assertFalse(self.run_page_wait(lambda _t: base[:3])[0])
        self.assertFalse(self.run_page_wait(lambda t:
            tuple((x, y + int(t * 40)) for x, y in base))[0])


if __name__ == '__main__':
    unittest.main()
