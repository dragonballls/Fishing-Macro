"""Checked keyboard and mouse hold/release events for Fish Fight actions."""
from __future__ import annotations

import ctypes
import math
import sys
import time
from ctypes import wintypes

SPACE_SCAN_CODE = 0x39
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
DEFAULT_HOLD_SECONDS = 0.04
MIN_HOLD_SECONDS = 0.01
MAX_HOLD_SECONDS = 0.12
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
_pynput_keyboard_controller = None
_pynput_key = None
_pynput_mouse_controller = None
_pynput_mouse_button = None


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
if _user32 is not None:
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    _user32.GetSystemMetrics.restype = ctypes.c_int


def _send_windows_key(scan_code: int, key_up: bool) -> None:
    """Send one checked Windows keyboard scan-code event."""
    if _user32 is None:
        raise RuntimeError("Windows SendInput is unavailable on this platform.")
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    event = _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(0, scan_code, flags, 0, 0))
    sent = int(_user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)))
    if sent != 1:
        error = ctypes.get_last_error()
        raise OSError(error, "Windows rejected Spacebar input. Keep Roblox focused and run Roblox and the macro at the same privilege level.")


def _validate_point(x: int, y: int) -> tuple[int, int]:
    if type(x) is not int or type(y) is not int or abs(x) > 100_000 or abs(y) > 100_000:
        raise ValueError("Mouse target coordinates must be integer screen coordinates.")
    return x, y


def _send_windows_mouse(x: int, y: int, button_up: bool) -> None:
    """Move to a screen point and send a checked left-button edge."""
    if _user32 is None:
        raise RuntimeError("Windows SendInput is unavailable on this platform.")
    x, y = _validate_point(x, y)
    # SM_*VIRTUALSCREEN metrics include monitors left/above the primary display.
    left = int(_user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
    top = int(_user32.GetSystemMetrics(77))   # SM_YVIRTUALSCREEN
    width = int(_user32.GetSystemMetrics(78)) # SM_CXVIRTUALSCREEN
    height = int(_user32.GetSystemMetrics(79))# SM_CYVIRTUALSCREEN
    if width < 1 or height < 1:
        raise RuntimeError("Windows did not report a valid virtual desktop.")
    if not (left <= x < left + width and top <= y < top + height):
        raise ValueError("Calibrated mouse target is outside the current virtual desktop; press F5 to recalibrate.")
    dx = round((x - left) * 65535 / max(1, width - 1))
    dy = round((y - top) * 65535 / max(1, height - 1))
    edge = MOUSEEVENTF_LEFTUP if button_up else MOUSEEVENTF_LEFTDOWN
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | edge
    event = _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(dx, dy, 0, flags, 0, 0))
    sent = int(_user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)))
    if sent != 1:
        error = ctypes.get_last_error()
        raise OSError(error, "Windows rejected left-mouse input. Keep Roblox focused and run Roblox and the macro at the same privilege level.")


def _get_pynput_keyboard():
    """Return a persistent controller so key-down/up use the same backend."""
    global _pynput_keyboard_controller, _pynput_key
    if _pynput_keyboard_controller is None:
        from pynput.keyboard import Controller, Key
        _pynput_keyboard_controller = Controller()
        _pynput_key = Key.space
    return _pynput_keyboard_controller, _pynput_key


def _get_pynput_mouse():
    """Return a persistent mouse controller and left-button enum."""
    global _pynput_mouse_controller, _pynput_mouse_button
    if _pynput_mouse_controller is None:
        from pynput.mouse import Button, Controller
        _pynput_mouse_controller = Controller()
        _pynput_mouse_button = Button.left
    return _pynput_mouse_controller, _pynput_mouse_button


def spacebar_down() -> None:
    """Begin holding Spacebar; caller must eventually call spacebar_up()."""
    if sys.platform == "win32":
        _send_windows_key(SPACE_SCAN_CODE, False)
    else:
        controller, key = _get_pynput_keyboard()
        controller.press(key)


def spacebar_up() -> None:
    """Release Spacebar. Safe to call during disarm and shutdown cleanup."""
    if sys.platform == "win32":
        _send_windows_key(SPACE_SCAN_CODE, True)
    else:
        controller, key = _get_pynput_keyboard()
        controller.release(key)


def mouse_left_down(x: int, y: int) -> None:
    """Move to the calibrated screen point and hold the left mouse button."""
    x, y = _validate_point(x, y)
    if sys.platform == "win32":
        _send_windows_mouse(x, y, False)
    else:
        controller, button = _get_pynput_mouse()
        controller.position = (x, y)
        controller.press(button)


def mouse_left_up(x: int, y: int) -> None:
    """Release the left mouse button at the original calibrated screen point."""
    x, y = _validate_point(x, y)
    if sys.platform == "win32":
        _send_windows_mouse(x, y, True)
    else:
        controller, button = _get_pynput_mouse()
        controller.position = (x, y)
        controller.release(button)


def press_spacebar(hold_seconds: float = DEFAULT_HOLD_SECONDS) -> None:
    """Send one bounded Spacebar tap, always attempting key-up after key-down."""
    if (isinstance(hold_seconds, bool)
        or not isinstance(hold_seconds, (int, float))
        or not math.isfinite(hold_seconds)
        or not MIN_HOLD_SECONDS <= hold_seconds <= MAX_HOLD_SECONDS):
        raise ValueError(f"hold_seconds must be between {MIN_HOLD_SECONDS:.2f} and {MAX_HOLD_SECONDS:.2f} seconds")
    spacebar_down()
    try:
        time.sleep(float(hold_seconds))
    finally:
        spacebar_up()
