"""Checked Spacebar hold/release events for the Fish Fight trigger."""
from __future__ import annotations

import ctypes
import math
import sys
import time
from ctypes import wintypes

SPACE_SCAN_CODE = 0x39
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
DEFAULT_HOLD_SECONDS = 0.04
MIN_HOLD_SECONDS = 0.01
MAX_HOLD_SECONDS = 0.12
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
_pynput_controller = None
_pynput_key = None

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]

class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]

_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
if _user32 is not None:
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT

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

def _get_pynput():
    """Return a persistent controller so press/release use the same backend."""
    global _pynput_controller, _pynput_key
    if _pynput_controller is None:
        from pynput.keyboard import Controller, Key
        _pynput_controller = Controller()
        _pynput_key = Key.space
    return _pynput_controller, _pynput_key

def spacebar_down() -> None:
    """Begin holding Spacebar; caller must eventually call spacebar_up()."""
    if sys.platform == "win32":
        _send_windows_key(SPACE_SCAN_CODE, False)
    else:
        controller, key = _get_pynput()
        controller.press(key)

def spacebar_up() -> None:
    """Release Spacebar. Safe to call during disarm and shutdown cleanup."""
    if sys.platform == "win32":
        _send_windows_key(SPACE_SCAN_CODE, True)
    else:
        controller, key = _get_pynput()
        controller.release(key)

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
