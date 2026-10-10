import threading
import unittest
from unittest.mock import Mock

from fishfight.input_gate import ClickOutcome, click_current_cursor_if_armed


class FakeState:
    def __init__(self, armed=True):
        self.lock = threading.Lock()
        self.armed = armed


class InputGateTests(unittest.TestCase):
    def test_disarmed_state_does_not_check_focus_or_click(self):
        state = FakeState(armed=False)
        focus = Mock(return_value=True)
        click = Mock()

        outcome = click_current_cursor_if_armed(state, focus, click)

        self.assertIs(outcome, ClickOutcome.DISARMED)
        focus.assert_not_called()
        click.assert_not_called()

    def test_focus_loss_disarms_and_never_clicks(self):
        state = FakeState(armed=True)
        focus = Mock(return_value=False)
        click = Mock()

        outcome = click_current_cursor_if_armed(state, focus, click)

        self.assertIs(outcome, ClickOutcome.FOCUS_LOST)
        self.assertFalse(state.armed)
        focus.assert_called_once_with()
        click.assert_not_called()

    def test_focused_armed_state_clicks_at_current_cursor_without_coordinates(self):
        state = FakeState(armed=True)
        focus = Mock(return_value=True)
        click = Mock()

        outcome = click_current_cursor_if_armed(state, focus, click)

        self.assertIs(outcome, ClickOutcome.SENT)
        self.assertTrue(state.armed)
        focus.assert_called_once_with()
        click.assert_called_once_with()

    def test_click_exception_disarms_and_propagates(self):
        state = FakeState(armed=True)
        focus = Mock(return_value=True)
        click = Mock(side_effect=OSError("injected input failure"))

        with self.assertRaisesRegex(OSError, "injected input failure"):
            click_current_cursor_if_armed(state, focus, click)

        self.assertFalse(state.armed)
        click.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
