"""Issue #38: optional yellow sampling must not select obsolete NPC logic.

All captures are synthetic. Fake mouse/keyboard devices record calls without
sending input, and the simulated clock avoids real waits or a live game.
"""
from types import SimpleNamespace
import unittest
from unittest import mock

import cv2
import numpy as np

from bloxfish import shop, vision
from bloxfish.capture import Rect
from bloxfish.config import Config
from bloxfish.inputs import SC_S


def closed_scenery():
    """Two gray scenery bands satisfy only the obsolete band counter."""
    image = np.full((350, 420, 3), 100, dtype=np.uint8)
    for top in (50, 170):
        image[top:top + 30, 20:400] = 150
    return image


def root_menu(rows=4):
    """Actual text over merged dark backing, rather than mocked row counts."""
    image = np.full((350, 420, 3), 240, dtype=np.uint8)
    image[25:340, 15:390] = 30
    for label, baseline in list(zip(
            ('Shop', 'Fishing Index', 'Job Stats', 'Nevermind'),
            (73, 153, 233, 313)))[:rows]:
        cv2.putText(image, label, (60, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                    .9, (255, 255, 255), 2, cv2.LINE_AA)
    return image


class FakeScreen:
    def __init__(self, image):
        self.image = image

    def grab(self, rect):
        return self.image[rect.top:rect.bottom, rect.left:rect.right].copy()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds


def make_engine(image, sampled=False):
    config = Config()
    config.colors.cap_dialogue_on = sampled
    config.shop.menu_left = config.shop.menu_top = 0.0
    config.shop.menu_right = config.shop.menu_bottom = 1.0
    config.shop.before_leave = config.shop.root_menu_settle = 0.0
    config.shop.after_nevermind = 0.0
    config.shop.menu_page_settle = .16
    clock = FakeClock()
    screen = FakeScreen(image)
    height, width = image.shape[:2]
    return SimpleNamespace(
        cfg=config, window=Rect(0, 0, width, height), screen=screen,
        bait_count=20, _buy_failures=0, _alive=lambda: True,
        _sleep=clock.advance, clock=clock,
        mouse=SimpleNamespace(click_at=mock.Mock(), move_to=mock.Mock()),
        keyboard=SimpleNamespace(tap=mock.Mock()), log=mock.Mock(),
        _rod_equipped=True, _shift_lock=False, _shift_lock_verified=False,
        _at_npc=False, _npc_repositioned=False,
    )


class CurrentDialogueTests(unittest.TestCase):
    def test_closed_gray_scenery_is_not_dialogue_without_optional_sample(self):
        image = closed_scenery()
        self.assertGreaterEqual(vision.menu_button_count(image), 2)
        self.assertEqual(vision.find_falling_menu_buttons(image), [])
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(image, sampled)
                self.assertEqual(shop.menu_items(engine), 0)
                self.assertFalse(shop.action_menu_open(engine))
                self.assertFalse(shop.in_dialogue(engine))
                # Retain compatibility with the existing no-page signature
                # representation, but never inherit the legacy counter's 2.
                signature = shop._menu_page_signature(engine)
                count = (len(signature) if signature and signature[0] != 'legacy'
                         else int(signature[1]) if signature else 0)
                self.assertEqual(count, 0)

    def test_closed_scene_does_not_consult_obsolete_band_counter(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(closed_scenery(), sampled)
                with mock.patch.object(vision, 'menu_button_count',
                                       return_value=4) as obsolete:
                    self.assertEqual(shop.menu_items(engine), 0)
                    self.assertFalse(shop.in_dialogue(engine))
                    signature = shop._menu_page_signature(engine)
                    self.assertNotEqual(signature, ('legacy', 4))
                obsolete.assert_not_called()

    def test_four_actual_root_labels_confirm_with_either_sample_setting(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(root_menu(), sampled)
                self.assertEqual(shop.menu_items(engine), 4)
                self.assertTrue(shop.in_dialogue(engine))
                with mock.patch.object(shop.time, 'perf_counter',
                                       side_effect=lambda: engine.clock.now), \
                        mock.patch.object(shop.time, 'sleep',
                                          side_effect=engine.clock.advance):
                    self.assertTrue(shop.wait_for_menu_page(engine, 'root', .8))
                self.assertGreaterEqual(engine.clock.now, .16)
                engine.keyboard.tap.assert_not_called()
                engine.mouse.click_at.assert_not_called()

    def test_three_falling_root_rows_cannot_confirm_four_row_page(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(root_menu(rows=3), sampled)
                self.assertEqual(shop.menu_items(engine), 3)
                self.assertTrue(shop.in_dialogue(engine))
                with mock.patch.object(shop.time, 'perf_counter',
                                       side_effect=lambda: engine.clock.now), \
                        mock.patch.object(shop.time, 'sleep',
                                          side_effect=engine.clock.advance):
                    self.assertFalse(shop.wait_for_menu_page(engine, 'root', .4))
                self.assertFalse(hasattr(engine, '_menu_page_witness'))
                engine.keyboard.tap.assert_not_called()
                engine.mouse.click_at.assert_not_called()

    def test_actual_yellow_catch_card_remains_detected_without_sample(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        image[780:825, 700:1220] = (30, 180, 220)
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(image, sampled)
                engine.cfg.shop.npc = 'none'
                self.assertTrue(vision.update30_dialogue_present(
                    image, engine.cfg.colors))
                self.assertTrue(shop.popup_up(engine))

    def test_blue_scenery_is_not_an_obsolete_catch_card(self):
        image = np.full((1080, 1920, 3), (110, 70, 35), dtype=np.uint8)
        self.assertGreater(vision.dialogue_overlay_frac(image), .6)
        self.assertFalse(vision.update30_dialogue_present(image))
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(image, sampled)
                self.assertFalse(shop.popup_up(engine))

    def test_current_npc_name_header_does_not_delay_route_as_catch_card(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(root_menu(), sampled)
                with mock.patch.object(shop, 'update30_dialogue_present',
                                       return_value=True):
                    self.assertFalse(shop.popup_up(engine))

    def test_leave_dialogue_closes_once_despite_legacy_scenery_bands(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(root_menu(), sampled)
                last = shop._falling_menu_buttons(engine)[-1]
                engine.mouse.click_at.side_effect = (
                    lambda _x, _y: setattr(engine.screen, 'image', closed_scenery()))
                with mock.patch.object(shop.time, 'perf_counter',
                                       side_effect=lambda: engine.clock.now), \
                        mock.patch.object(shop.time, 'sleep',
                                          side_effect=engine.clock.advance), \
                        mock.patch.object(vision, 'menu_button_count', return_value=2):
                    self.assertTrue(shop.leave_dialogue(engine))
                engine.mouse.click_at.assert_called_once_with(*last)
                engine.keyboard.tap.assert_not_called()
                self.assertFalse(shop.in_dialogue(engine))

    def test_anchor_closes_live_menu_then_verifies_lock_without_movement(self):
        for sampled in (False, True):
            with self.subTest(sampled=sampled):
                engine = make_engine(root_menu(), sampled)
                last = shop._falling_menu_buttons(engine)[-1]
                engine.mouse.click_at.side_effect = (
                    lambda _x, _y: setattr(engine.screen, 'image', closed_scenery()))
                def verified_shift(target, on):
                    target._shift_lock = on
                    target._shift_lock_verified = True
                    return True
                with mock.patch.object(shop.time, 'perf_counter',
                                       side_effect=lambda: engine.clock.now), \
                        mock.patch.object(shop.time, 'sleep',
                                          side_effect=engine.clock.advance), \
                        mock.patch.object(vision, 'menu_button_count', return_value=2), \
                        mock.patch.object(shop, 'set_shift_lock',
                                          side_effect=verified_shift) as shift:
                    self.assertTrue(shop.establish_fishing_anchor(engine))
                engine.mouse.click_at.assert_called_once_with(*last)
                engine.mouse.move_to.assert_not_called()
                engine.keyboard.tap.assert_not_called()
                self.assertFalse(any(call.args and call.args[0] == SC_S
                                     for call in engine.keyboard.tap.call_args_list))
                self.assertEqual([call.args[1] for call in shift.call_args_list],
                                 [False, True])
                self.assertTrue(engine._shift_lock_verified)
                self.assertFalse(engine._at_npc)


if __name__ == '__main__':
    unittest.main()
