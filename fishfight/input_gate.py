"""Small, testable gate for cursor-position mouse input."""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Protocol


class ArmedState(Protocol):
    """Minimal thread-safe state contract required by the input gate."""

    lock: Any
    armed: bool


class ClickOutcome(Enum):
    DISARMED = "disarmed"
    FOCUS_LOST = "focus_lost"
    SENT = "sent"


def click_current_cursor_if_armed(
    state: ArmedState,
    focus_check: Callable[[], bool],
    click: Callable[[], object],
) -> ClickOutcome:
    """Click without coordinates only if armed and Roblox still has focus.

    Locking spans the final state/focus check and the one click call, so Esc,
    F6, and F9 cannot finish their disarm transition before a late click.
    The callback is intentionally called with no coordinates: the cursor is
    neither moved nor re-targeted by this helper.
    """
    with state.lock:
        if not state.armed:
            return ClickOutcome.DISARMED
        if not focus_check():
            state.armed = False
            return ClickOutcome.FOCUS_LOST
        try:
            click()
        except Exception:
            state.armed = False
            raise
        return ClickOutcome.SENT
