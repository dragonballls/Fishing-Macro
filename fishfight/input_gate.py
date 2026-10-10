"""Thread-safe gate for any timed input sent by the macro."""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Protocol

class ArmedState(Protocol):
    """Minimal thread-safe state contract required by the input gate."""
    lock: Any
    armed: bool

class InputOutcome(Enum):
    DISARMED = "disarmed"
    FOCUS_LOST = "focus_lost"
    SENT = "sent"

# Backward-compatible name for existing tests or click-specific callers.
ClickOutcome = InputOutcome

def send_input_if_armed(
    state: ArmedState,
    focus_check: Callable[[], bool],
    action: Callable[[], object],
) -> InputOutcome:
    """Run one input action only if armed and Roblox still has focus.

    The lock spans the final state/focus check and the input action, so Esc,
    F6 and F9 cannot finish their disarm transition before a late input.
    The action is injected by the caller (for example, a Spacebar press).
    """
    with state.lock:
        if not state.armed:
            return InputOutcome.DISARMED
        if not focus_check():
            state.armed = False
            return InputOutcome.FOCUS_LOST
        try:
            action()
        except Exception:
            state.armed = False
            raise
        return InputOutcome.SENT

def click_current_cursor_if_armed(
    state: ArmedState,
    focus_check: Callable[[], bool],
    click: Callable[[], object],
) -> InputOutcome:
    """Compatibility wrapper for older click-specific callers."""
    return send_input_if_armed(state, focus_check, click)
