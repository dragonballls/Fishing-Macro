"""Fish-only routing regressions. No game captures or real input are used."""
from __future__ import annotations

from dataclasses import asdict
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest import mock

import numpy as np

from bloxfish import engine as engine_mod, shop
from bloxfish.capture import Rect
from bloxfish.config import Config
from bloxfish.routes import buying_enabled, npc_route_enabled, selling_enabled
from easy_run import App, PreparationItem
import customtkinter as ctk


def fake_engine():
    engine = object.__new__(engine_mod.FishingEngine)
    engine.cfg = Config()
    engine.cfg.shop.npc = 'none'
    engine.window = Rect(0, 0, 1920, 1080)
    engine.mouse = mock.Mock()
    engine.keyboard = mock.Mock()
    engine.screen = mock.Mock()
    engine.log = mock.Mock()
    engine._sleep = mock.Mock()
    engine._run_lock = threading.Lock()
    engine.running = False
    engine._stop = False
    engine._shift_lock = engine._shift_lock_verified = False
    engine._buy_failures = engine._since_sell = 0
    engine.bait_count = 1
    engine.stats = engine_mod.Stats()
    engine._cycle = mock.Mock(side_effect=engine.stop)
    return engine


class RoutePolicyTests(unittest.TestCase):
    def test_disabled_npc_overrides_saved_selling_and_bait_count(self):
        cfg = Config()
        for npc in ('none', 'off', '', ' OFF ', 'NONE'):
            cfg.shop.npc = npc
            for count in (None, 0, 1, 80):
                with self.subTest(npc=npc, count=count):
                    self.assertFalse(buying_enabled(cfg, count))
                    self.assertFalse(selling_enabled(cfg))
                    self.assertFalse(npc_route_enabled(cfg, count))

    def test_no_tracking_does_not_disable_an_enabled_sale_route(self):
        cfg = Config()
        self.assertFalse(buying_enabled(cfg, None))
        self.assertTrue(npc_route_enabled(cfg, None))
        cfg.sell.every = 0
        self.assertFalse(npc_route_enabled(cfg, None))
        self.assertTrue(npc_route_enabled(cfg, 1))

    def test_zero_purchase_and_failure_limit_disable_only_buying(self):
        cfg = Config()
        cfg.sell.enabled = False
        cfg.shop.bait_per_purchase = 0
        self.assertFalse(npc_route_enabled(cfg, 1))
        cfg.shop.bait_per_purchase = 20
        self.assertTrue(buying_enabled(cfg, 1, 2))
        self.assertFalse(npc_route_enabled(cfg, 1, 3))
        cfg.sell.enabled = True
        self.assertTrue(npc_route_enabled(cfg, 1, 3))

    def test_config_roundtrip_preserves_disabled_choice_and_calibration(self):
        cfg = Config()
        cfg.shop.npc = 'none'
        cfg.shop.center = (.72, .67)
        cfg.shop.menu_item3 = (.8, .6)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            cfg.save(path)
            loaded = Config.load(path)
        self.assertEqual(loaded.shop.npc, 'none')
        self.assertEqual(loaded.shop.center, (.72, .67))
        self.assertEqual(loaded.shop.menu_item3, (.8, .6))
        self.assertTrue(loaded.sell.enabled)  # preserved, not silently erased
        self.assertFalse(npc_route_enabled(loaded, 1))


class FishOnlyEngineTests(unittest.TestCase):
    def test_start_and_restart_skip_all_npc_and_shift_helpers_on_both_platforms(self):
        for platform in ('windows', 'sober-x11'):
            for reason in ('none', 'off', '', 'untracked', 'zero-purchase', 'zero-attempts'):
                with self.subTest(platform=platform, reason=reason), \
                     mock.patch.dict(os.environ, {'BLOXFISH_PLATFORM': platform}):
                    engine = fake_engine()
                    if reason in ('none', 'off', ''):
                        engine.cfg.shop.npc = reason
                    else:
                        engine.cfg.shop.npc = 'fisherman'
                        engine.cfg.sell.every = 0
                        if reason == 'untracked':
                            engine.bait_count = None
                        elif reason == 'zero-purchase':
                            engine.cfg.shop.bait_per_purchase = 0
                        else:
                            engine.cfg.shop.max_failures = 0
                    with mock.patch.object(engine_mod, 'focus_game_window', return_value=True), \
                         mock.patch.multiple(shop, establish_fishing_anchor=mock.DEFAULT,
                                             enter_fishing_stance=mock.DEFAULT,
                                             set_shift_lock=mock.DEFAULT,
                                             in_dialogue=mock.DEFAULT) as guards:
                        engine.run()
                        engine.run()
                    for helper in guards.values():
                        helper.assert_not_called()
                    self.assertEqual(engine._cycle.call_count, 2)
                    self.assertFalse(engine._at_npc)
                    self.assertFalse(engine.running)
                    self.assertFalse(engine._run_lock.locked())
                    engine.keyboard.tap.assert_not_called()
                    engine.mouse.position.assert_not_called()
                    engine.mouse.click_at.assert_not_called()
                    engine.mouse.move_to.assert_not_called()
                    engine.screen.grab.assert_not_called()

    def test_sell_only_and_buy_only_still_require_the_original_anchor(self):
        for count, sell in ((None, True), (1, False)):
            with self.subTest(count=count, sell=sell):
                engine = fake_engine()
                engine.cfg.shop.npc = 'fisherman'
                engine.cfg.sell.enabled = sell
                engine.bait_count = count
                with mock.patch.object(engine_mod, 'focus_game_window', return_value=True), \
                     mock.patch.object(shop, 'establish_fishing_anchor', return_value=False) as anchor:
                    engine.run()
                anchor.assert_called_once_with(engine)
                engine._cycle.assert_not_called()
                self.assertFalse(engine.running)

    def prepare_cast(self, engine):
        engine._minigame_running = mock.Mock(return_value=False)
        engine.cfg.timing.cast_hold = 0
        engine.cfg.timing.max_cast_attempts = 1
        engine._meter_miss = mock.Mock()
        engine.meter_thr = 30

    def test_casts_with_unreadable_cursor_without_shift_lock_checks(self):
        engine = fake_engine()
        self.prepare_cast(engine)
        engine.cfg.timing.verify_cast = False
        engine.mouse.position.side_effect = OSError('cursor unavailable')
        with mock.patch.object(shop, 'fishing_shift_lock_ready') as verify:
            self.assertTrue(engine._do_cast())
        verify.assert_not_called()
        engine.mouse.position.assert_not_called()
        engine.mouse.press.assert_called_once()
        self.assertFalse(engine._stop)

    def test_failed_cast_never_checks_or_closes_an_npc_menu(self):
        engine = fake_engine()
        self.prepare_cast(engine)
        with mock.patch.object(shop, 'escape_dialogue') as escape, \
             mock.patch.object(shop, 'fishing_shift_lock_ready') as verify:
            self.assertFalse(engine._do_cast())
        escape.assert_not_called()
        verify.assert_not_called()
        engine.keyboard.tap.assert_not_called()
        engine.mouse.click_at.assert_not_called()
        engine.mouse.release.assert_called()

    def test_live_minigame_still_prevents_a_cast(self):
        engine = fake_engine()
        self.prepare_cast(engine)
        engine._minigame_running.return_value = True
        engine.cfg.timing.max_reel_seconds = 0
        self.assertFalse(engine._do_cast())
        engine.mouse.press.assert_not_called()

    def test_low_bait_never_schedules_or_enters_disabled_shop_actions(self):
        engine = fake_engine()
        engine._spend_bait()
        self.assertEqual(engine.bait_count, 0)
        self.assertFalse(engine._needs_bait())
        self.assertFalse(engine._needs_sell())
        self.assertNotIn('buying at', engine.log.call_args.args[0])
        with mock.patch.object(shop, 'buy') as buy, mock.patch.object(shop, 'sell') as sell:
            engine._buy_bait()
            self.assertFalse(engine._sell_fish())
        buy.assert_not_called()
        sell.assert_not_called()
        self.assertEqual(engine.bait_count, 0)

    def test_entire_fishing_cycle_continues_without_buying_or_selling(self):
        engine = fake_engine()
        engine.bait_count = 0
        engine._since_sell = 1000
        engine._look_for_bar = mock.Mock(return_value=None)
        engine._do_cast = mock.Mock(return_value=True)
        engine._wait_for_bite = mock.Mock(return_value=True)
        engine._reel = mock.Mock(return_value=True)
        engine._dismiss_catch = mock.Mock()
        engine._wait_bar_clear = mock.Mock()
        engine._buy_bait = mock.Mock(side_effect=AssertionError('buying disabled'))
        engine._sell_fish = mock.Mock(side_effect=AssertionError('selling disabled'))
        engine_mod.FishingEngine._cycle(engine)
        for step in (engine._do_cast, engine._wait_for_bite, engine._reel,
                     engine._dismiss_catch, engine._wait_bar_clear):
            step.assert_called_once()
        engine._buy_bait.assert_not_called()
        engine._sell_fish.assert_not_called()

    def test_failure_limit_does_not_reenter_buying_on_subsequent_cycles(self):
        engine = fake_engine()
        engine.cfg.shop.npc = 'fisherman'
        engine.cfg.sell.every = 0
        with mock.patch.object(shop, 'buy', return_value=False) as buy:
            for _ in range(5):
                engine._buy_bait()
        self.assertEqual(buy.call_count, engine.cfg.shop.max_failures)
        self.assertIsNone(engine.bait_count)
        self.assertFalse(npc_route_enabled(engine.cfg, engine.bait_count, engine._buy_failures))
        self.assertFalse(engine._needs_bait())
        self.assertEqual(engine.stats.purchases, 0)

    def test_fish_only_watchdog_still_stops_and_releases_input(self):
        engine = fake_engine()
        engine.running = True
        engine._last_response_at = 0
        engine._last_response_label = 'session start'
        with mock.patch.object(engine_mod.time, 'perf_counter', return_value=301):
            self.assertFalse(engine._alive())
        self.assertTrue(engine.safety_stopped)
        engine.mouse.release.assert_called_once()

    def test_catch_popup_detection_never_scans_an_npc_area(self):
        engine = fake_engine()
        engine.cfg.colors.cap_dialogue_on = True
        engine.screen.grab.return_value = np.zeros((100, 100, 3), np.uint8)
        with mock.patch.object(shop, '_falling_menu_buttons') as menu:
            self.assertFalse(shop.popup_up(engine))
        menu.assert_not_called()
        engine.screen.grab.assert_called_once_with(engine.window)

    def test_recipe_note_stops_without_a_blind_shift_toggle_or_click(self):
        engine = fake_engine()
        with mock.patch.object(shop, 'learn_up', return_value=True), \
             mock.patch.object(shop, 'set_shift_lock') as toggle:
            self.assertFalse(shop.clear_recipe_note(engine))
        toggle.assert_not_called()
        engine.mouse.click_at.assert_not_called()
        engine.keyboard.tap.assert_not_called()
        self.assertTrue(engine._stop)
        self.assertIn('Clear Learn manually', engine.log.call_args.args[0])


class FishOnlySetupTests(unittest.TestCase):
    def test_preparation_wrap_is_event_driven_and_uses_logical_scaled_width(self):
        label = mock.Mock()
        current = [720]
        label.cget.side_effect = lambda _key: current[0]
        label.configure.side_effect = lambda **kwargs: current.__setitem__(0, kwargs['wraplength'])
        label._reverse_widget_scaling.side_effect = lambda width: width / 1.25
        PreparationItem._bind_text_wrap(label, 720)
        resize = label.bind.call_args_list[0].args[1]
        resize(NS(width=1))
        label.configure.assert_not_called()
        resize(NS(width=750))
        resize(NS(width=750))
        label.after.assert_called_once()
        label.configure.assert_not_called()  # never redraw inside Configure
        label.after.call_args.args[1]()
        self.assertEqual(current[0], 596)
        resize(NS(width=750))
        label.configure.assert_called_once()

    def test_terminal_no_buy_still_requests_rod_slot_and_shows_manual_preparation(self):
        path = Path(__file__).resolve().parents[1] / 'run.py'
        spec = importlib.util.spec_from_file_location('_fish_only_terminal', path)
        terminal = importlib.util.module_from_spec(spec)
        with mock.patch('_bootstrap.ensure_requirements', return_value=True):
            spec.loader.exec_module(terminal)
        cfg = Config()
        engine = NS(bait_count=None)
        with mock.patch.object(terminal, '_ask', side_effect=['n', '5', '80', '']), \
             mock.patch('builtins.print') as output:
            self.assertTrue(terminal._setup_prompts(cfg, engine))
        lines = '\n'.join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertEqual(cfg.rod_slot, '5')
        self.assertEqual(engine.bait_count, 80)
        self.assertIn('Fish-only: choose your fishing position', lines)
        self.assertIn('Set Shift Lock yourself', lines)
        self.assertNotIn('Stand at the NPC', lines)
        self.assertNotIn('will restock at', lines)

    def test_preparation_uses_pending_draft_without_changing_saved_settings(self):
        app = object.__new__(App)
        app.cfg = Config()
        before = asdict(app.cfg)
        for npc, bait, sell, expected in (
                ("Don't buy", '80', '100', False),
                ('Fisherman', '', '0', False),
                ('Fisherman', '', '100', True),
                ('Fisherman', '80', '0', True)):
            app._form_draft = dict(npc=npc, bait=bait, sell=sell, amount='90')
            cfg, count = app._route_preview()
            self.assertEqual(npc_route_enabled(cfg, count), expected)
            self.assertEqual(asdict(app.cfg), before)

    def test_finish_saves_no_buy_without_erasing_sell_interval_or_calibration(self):
        app = object.__new__(App)
        app.cfg = Config()
        app.cfg.shop.center = (.72, .67)
        app.cfg.save = mock.Mock()
        app._page = 'checklist'
        app._form_draft = dict(npc="Don't buy", bait='80', sell='100', amount='90', rod='5')
        app._prep_error = mock.Mock()
        app._build_runner = mock.Mock()
        app._finish_preparation()
        self.assertEqual(app.cfg.shop.npc, 'none')
        self.assertEqual(app.cfg.sell.every, 100)
        self.assertEqual(app.cfg.shop.center, (.72, .67))
        self.assertFalse(npc_route_enabled(app.cfg, app.bait))
        app.cfg.save.assert_called_once()
        app._build_runner.assert_called_once()


@unittest.skipUnless(os.environ.get('BLOXFISH_TEST_GUI') == '1', 'opt-in real Tk UI test')
class FishOnlyUITests(unittest.TestCase):
    def test_mode_specific_guide_resize_toggle_back_and_finish(self):
        errors = []
        with mock.patch('easy_run.Config.load', return_value=Config()), \
             mock.patch.object(App, '_play_startup'), \
             mock.patch('easy_run.FishingEngine', side_effect=AssertionError('no real backend')):
            app = App()
        app.report_callback_exception = lambda *exc: errors.append(exc)
        app.cfg.save = mock.Mock()
        try:
            for npc, bait, sell, uses_npc in (("Don't buy", '80', '100', False),
                                            ('Fisherman', '', '0', False),
                                            ('Fisherman', '80', '0', True)):
                app._build_form()
                app.v_npc.set(npc)
                app.v_bait.set(bait)
                app.v_sell.set(sell)
                app._refresh_profile()
                self.assertEqual(app.profile_npc.cget('text'),
                                 'Fisherman route' if uses_npc else 'Fish-only / no NPC')
                app._open_preparation()  # does not apply saved config
                app.cfg.save.assert_not_called()
                self.assertEqual(len(app._prep_items), 11)
                first = app._prep_items[0]
                self.assertEqual('NPC, right on the edge' in first.title_button.cget('text'), uses_npc)
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                for width, height in ((780, 560), (1080, 740), (1440, 900)):
                    app.geometry(f'{width}x{height}')
                    app.update()
                    self.assertTrue(app.go.winfo_ismapped())
                    for _ in range(4):
                        first.toggle()
                        until = time.perf_counter() + .18
                        while time.perf_counter() < until:
                            app.update()
                            time.sleep(.01)
                    self.assertTrue(first._open)
                    for label in first._wrapped_labels:
                        self.assertLessEqual(label.cget('wraplength'),
                                             label._reverse_widget_scaling(label.winfo_width()))
                    if not uses_npc and os.environ.get('BLOXFISH_TEST_SCREENSHOTS'):
                        from PIL import ImageGrab
                        folder = Path(os.environ['BLOXFISH_TEST_SCREENSHOTS'])
                        folder.mkdir(parents=True, exist_ok=True)
                        x, y = app.winfo_rootx(), app.winfo_rooty()
                        ImageGrab.grab((x, y, x + app.winfo_width(),
                                       y + app.winfo_height())).save(
                            folder / f'fish-only-{width}x{height}.png')
                if not uses_npc:
                    from easy_run import NPCPositionSimulation
                    self.assertFalse(any(isinstance(w, NPCPositionSimulation)
                                         for w in descendants(app)))
                    if os.environ.get('BLOXFISH_TEST_SCREENSHOTS'):
                        from PIL import ImageGrab
                        folder = Path(os.environ['BLOXFISH_TEST_SCREENSHOTS'])
                        folder.mkdir(parents=True, exist_ok=True)
                        app.geometry('1080x740')
                        app.update()
                        x, y = app.winfo_rootx(), app.winfo_rooty()
                        ImageGrab.grab((x, y, x + app.winfo_width(),
                                       y + app.winfo_height())).save(folder / 'fish-only-preparation.png')
                app._build_form()  # Back restores the unsaved answers
                self.assertEqual(app.v_npc.get(), npc)
            app.v_npc.set("Don't buy")
            app._open_preparation()
            app.v_ready.set(True)
            app.go.configure(state='normal')
            with mock.patch.object(app, '_build_runner') as runner:
                app.go.invoke()
                runner.assert_called_once()
            self.assertEqual(app.cfg.shop.npc, 'none')
            app.cfg.save.assert_called_once()
        finally:
            # A subsequent test creates another Tk root in this interpreter.
            # Remove pending test-root CTk callbacks before destroying it so
            # they cannot leak into that unrelated event loop.
            for callback in app.tk.call('after', 'info'):
                app.after_cancel(callback)
            app.destroy()
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
