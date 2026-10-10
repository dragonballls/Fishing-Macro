import math
import unittest
from unittest.mock import call, patch

from fishfight import input_events

class SpacebarInputTests(unittest.TestCase):
    def test_down_and_up_map_to_scan_code_transitions(self):
        with patch.object(input_events.sys, "platform", "win32"), patch.object(input_events, "_send_windows_key") as send:
            input_events.spacebar_down()
            input_events.spacebar_up()
        self.assertEqual(send.call_args_list, [
            call(input_events.SPACE_SCAN_CODE, False),
            call(input_events.SPACE_SCAN_CODE, True),
        ])

    def test_windows_backend_sends_space_scan_code_down_then_up(self):
        with (
            patch.object(input_events.sys, "platform", "win32"),
            patch.object(input_events, "_send_windows_key") as send,
            patch.object(input_events.time, "sleep") as sleep,
        ):
            input_events.press_spacebar()
        self.assertEqual(send.call_args_list, [
            call(input_events.SPACE_SCAN_CODE, False),
            call(input_events.SPACE_SCAN_CODE, True),
        ])
        sleep.assert_called_once_with(input_events.DEFAULT_HOLD_SECONDS)

    def test_tap_releases_space_if_hold_wait_fails(self):
        with (
            patch.object(input_events.sys, "platform", "win32"),
            patch.object(input_events, "_send_windows_key") as send,
            patch.object(input_events.time, "sleep", side_effect=RuntimeError("test")) as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "test"):
                input_events.press_spacebar()
        self.assertEqual(send.call_args_list, [
            call(input_events.SPACE_SCAN_CODE, False),
            call(input_events.SPACE_SCAN_CODE, True),
        ])
        sleep.assert_called_once_with(input_events.DEFAULT_HOLD_SECONDS)

    def test_mouse_button_down_and_up_use_the_calibrated_screen_point(self):
        with (
            patch.object(input_events.sys, "platform", "win32"),
            patch.object(input_events, "_send_windows_mouse") as send,
        ):
            input_events.mouse_left_down(504, 791)
            input_events.mouse_left_up(504, 791)
        self.assertEqual(send.call_args_list, [
            call(504, 791, False),
            call(504, 791, True),
        ])

    def test_mouse_action_rejects_invalid_coordinates_before_sending(self):
        with patch.object(input_events.sys, "platform", "win32"), patch.object(input_events, "_send_windows_mouse") as send:
            for point in ((True, 10), (10, "20"), (100001, 10)):
                with self.subTest(point=point):
                    with self.assertRaises(ValueError):
                        input_events.mouse_left_down(*point)
        send.assert_not_called()

    def test_rejects_invalid_or_unbounded_tap_holds_before_sending(self):
        invalid = (0, -0.1, 0.5, math.nan, math.inf, True, "0.04")
        with patch.object(input_events.sys, "platform", "win32"), patch.object(input_events, "_send_windows_key") as send:
            for duration in invalid:
                with self.subTest(duration=duration):
                    with self.assertRaises(ValueError):
                        input_events.press_spacebar(duration)
        send.assert_not_called()

if __name__ == "__main__":
    unittest.main()
