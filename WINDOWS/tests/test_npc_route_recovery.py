"""Issue #38: image-driven NPC transitions, bounded retries and safe closure."""
from contextlib import contextmanager
import unittest
from unittest import mock

import cv2
import numpy as np

from bloxfish import shop
from test_current_dialogue import make_engine, root_menu


def page(labels):
    image = np.full((350, 420, 3), 120, dtype=np.uint8)
    image[25:340, 15:390] = 30
    for label, baseline in zip(labels, (73, 153, 233, 313)[-len(labels):]):
        cv2.putText(image, label, (60, baseline), cv2.FONT_HERSHEY_SIMPLEX,
                    .9, (255, 255, 255), 2, cv2.LINE_AA)
    return image


def scenery():
    image = np.full((350, 420, 3), 120, dtype=np.uint8)
    for top in (50, 170):
        image[top:top + 40] = 30
    return image


@contextmanager
def clock_for(engine):
    with mock.patch.object(shop.time, 'perf_counter', side_effect=lambda: engine.clock.now), \
            mock.patch.object(shop.time, 'sleep', side_effect=engine.clock.advance):
        yield


class NPCRecoveryTests(unittest.TestCase):
    def test_closed_dark_scenery_requires_exactly_one_exit_click(self):
        engine = make_engine(root_menu())
        engine.mouse.click_at.side_effect = lambda *_: setattr(engine.screen, 'image', scenery())
        with clock_for(engine):
            self.assertTrue(shop.leave_dialogue(engine))
        self.assertEqual(engine.mouse.click_at.call_count, 1)
        engine.keyboard.tap.assert_not_called()

    def test_missed_exit_retries_only_the_same_confirmed_root(self):
        engine = make_engine(root_menu())
        def click(*_):
            if engine.mouse.click_at.call_count == 2:
                engine.screen.image = scenery()
        engine.mouse.click_at.side_effect = click
        with clock_for(engine):
            self.assertTrue(shop.leave_dialogue(engine))
        self.assertEqual(engine.mouse.click_at.call_count, 2)
        self.assertEqual(*engine.mouse.click_at.call_args_list)

    def test_exit_never_retargets_an_unrelated_short_stack(self):
        engine = make_engine(root_menu())
        engine.mouse.click_at.side_effect = lambda *_: setattr(
            engine.screen, 'image', page(('Basic Bait', 'Back')))
        with clock_for(engine):
            self.assertFalse(shop.leave_dialogue(engine))
        self.assertEqual(engine.mouse.click_at.call_count, 1)

    def test_changed_frame_between_page_proof_and_click_sends_nothing(self):
        engine = make_engine(root_menu())
        with clock_for(engine):
            self.assertTrue(shop.wait_for_menu_page(engine, 'root', .8))
            engine.screen.image = page(('Basic Bait', 'Back'))
            self.assertFalse(shop.click_menu_action(engine, 'root', 'shop'))
        engine.mouse.click_at.assert_not_called()

    def test_capture_failure_does_not_prove_dialogue_closed(self):
        engine = make_engine(root_menu())
        def click(*_):
            engine.screen.grab = mock.Mock(side_effect=OSError('capture unavailable'))
        engine.mouse.click_at.side_effect = click
        with clock_for(engine):
            self.assertFalse(shop.leave_dialogue(engine))
        self.assertEqual(engine.mouse.click_at.call_count, 1)

    def test_one_missing_frame_is_not_a_successful_exit(self):
        engine = make_engine(root_menu())
        original_grab = engine.screen.grab
        until = [None]
        def click(*_):
            if engine.mouse.click_at.call_count == 1:
                until[0] = engine.clock.now + .08
            else:
                engine.screen.image = scenery()
        def grab(rect):
            if until[0] is not None and engine.clock.now < until[0]:
                return scenery()[rect.top:rect.bottom, rect.left:rect.right]
            return original_grab(rect)
        engine.mouse.click_at.side_effect = click
        engine.screen.grab = grab
        with clock_for(engine):
            self.assertTrue(shop.leave_dialogue(engine))
        self.assertEqual(engine.mouse.click_at.call_count, 2)

    def test_late_destination_is_accepted_without_repeating_source_action(self):
        engine = make_engine(root_menu())
        original_grab = engine.screen.grab
        transition_at = [None]
        def click(*_):
            transition_at[0] = engine.clock.now + .25
        def grab(rect):
            if transition_at[0] is not None and engine.clock.now >= transition_at[0]:
                engine.screen.image = page(('Buy Bait', 'Sell Fish', 'Nevermind'))
            return original_grab(rect)
        engine.mouse.click_at.side_effect = click
        engine.screen.grab = grab
        with clock_for(engine):
            self.assertTrue(shop._click_menu_action_until(
                engine, 'root', 'shop', done=lambda: False,
                tries=4, wait=.24, next_page='shop'))
        self.assertEqual(engine.mouse.click_at.call_count, 1)

    def test_cancellation_during_exit_sends_no_click(self):
        engine = make_engine(root_menu())
        engine._alive = lambda: engine.clock.now < .1
        with clock_for(engine):
            self.assertFalse(shop.leave_dialogue(engine))
        engine.mouse.click_at.assert_not_called()

    def test_failed_capture_blocks_approach_movement(self):
        engine = make_engine(root_menu())
        engine.screen.grab = mock.Mock(side_effect=OSError('capture unavailable'))
        engine._rod_equipped = False
        with clock_for(engine), mock.patch.object(shop, 'wait_popup_clear'):
            self.assertFalse(shop.open_npc_dialogue(engine))
        engine.keyboard.tap.assert_not_called()

    def test_failed_route_recovery_stops_instead_of_restoring_fishing(self):
        for route in ('buy', 'sell'):
            with self.subTest(route=route):
                engine = make_engine(root_menu())
                engine.cfg.shop.npc = 'fisherman'
                engine.stop = mock.Mock()
                with mock.patch.object(shop, 'open_npc_dialogue', return_value=False), \
                        mock.patch.object(shop, '_recover', return_value=False), \
                        mock.patch.object(shop, 'enter_fishing_stance') as fishing:
                    result = shop.buy(engine, 20) if route == 'buy' else shop.sell(engine)
                self.assertFalse(result)
                engine.stop.assert_called_once_with()
                fishing.assert_not_called()
                engine.mouse.click_at.assert_not_called()
                engine.keyboard.tap.assert_not_called()

    def test_unknown_recovery_page_never_uses_blind_bottom_clicks(self):
        engine = make_engine(page(('Buy Bait', 'Sell Fish', 'Nevermind')))
        with clock_for(engine), mock.patch.object(shop, 'craft_up', return_value=False):
            self.assertFalse(shop._recover(engine))
        engine.mouse.click_at.assert_not_called()
        engine.keyboard.tap.assert_not_called()

    def test_cancelled_anchor_does_not_enable_shift_lock_after_exit(self):
        engine = make_engine(root_menu())
        engine.cfg.shop.after_nevermind = .5
        engine._alive = lambda: engine.clock.now < .2
        with clock_for(engine), \
                mock.patch.object(shop, 'open_npc_dialogue', return_value=True), \
                mock.patch.object(shop, 'leave_dialogue', return_value=True), \
                mock.patch.object(shop, 'enter_fishing_stance') as fishing:
            self.assertFalse(shop.establish_fishing_anchor(engine))
        fishing.assert_not_called()
        engine.keyboard.tap.assert_not_called()

    def run_route(self, selling):
        engine = make_engine(root_menu())
        engine.cfg.shop.npc = 'fisherman'
        images = {
            'root': root_menu(), 'shop': page(('Buy Bait', 'Sell Fish', 'Nevermind')),
            'bait': page(('Basic Bait', 'Back')), 'confirm': page(('Confirm', 'Nevermind')),
            'craft': scenery(), 'closed': scenery(),
        }
        state = ['root']
        steps = []
        plus = shop._abs(engine.window, engine.cfg.shop.craft_plus)
        craft = shop._abs(engine.window, engine.cfg.shop.craft_button)
        def click(x, y):
            current = state[0]
            steps.append(current)
            if current == 'craft':
                self.assertIn((x, y), (plus, craft))
                dest = 'bait' if (x, y) == craft else 'craft'
            else:
                rows = shop._falling_menu_buttons(engine)
                if current == 'root':
                    chosen = -1 if steps.count('root') > 1 else 0
                    dest = 'closed' if chosen == -1 else 'shop'
                elif current == 'shop':
                    chosen, dest = (1, 'confirm') if selling else (0, 'bait')
                elif current == 'confirm':
                    chosen, dest = 0, 'closed'
                else:
                    chosen = -1 if steps.count('bait') > 1 else 0
                    dest = 'root' if chosen == -1 else 'craft'
                self.assertEqual((x, y), rows[chosen])
            state[0] = dest
            engine.screen.image = images[dest]
        engine.mouse.click_at.side_effect = click
        with clock_for(engine), mock.patch.object(shop, 'craft_up',
                                                 side_effect=lambda _: state[0] == 'craft'), \
                mock.patch.object(shop, 'enter_fishing_stance', return_value=True):
            result = shop.sell(engine) if selling else shop.buy(engine, 20)
        self.assertTrue(result)
        self.assertEqual(state[0], 'closed')
        engine.keyboard.tap.assert_not_called()
        return steps

    def test_full_buy_route_and_return_to_fishing(self):
        self.assertEqual(self.run_route(False),
                         ['root', 'shop', 'bait', 'craft', 'craft', 'bait', 'root'])

    def test_full_sell_route_and_return_to_fishing(self):
        self.assertEqual(self.run_route(True), ['root', 'shop', 'confirm'])


if __name__ == '__main__':
    unittest.main()
