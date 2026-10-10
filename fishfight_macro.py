"""Screen-based helper for the Blox Fruits Sharkman Master Fish Fight.

Hotkeys:
  F6  Calibrate the gauge rectangle
  F7  Arm/disarm automatic left-clicks at the current cursor (starts disarmed)
  F8  Toggle the visual detector preview
  Esc Disarm immediately
  F9  Exit

Only visible pixels and a normal left-click at the current cursor are used.
No client injection, remote calls, memory reading, or game-file modification.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import mss
import numpy as np
import pyautogui
from pynput import keyboard

from fishfight.timing import MotionHistory, time_to_alignment
from fishfight.vision import VisionConfig, detect_gauge, draw_diagnostics

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DEFAULT_CONFIG: dict[str, Any] = {
    "roi": None,
    "dry_run": True,
    "poll_hz": 90,
    "prediction_horizon_s": 0.45,
    "press_lead_s": 0.020,
    "green_h_min": 35,
    "green_h_max": 95,
    "green_s_min": 70,
    "green_v_min": 70,
    "white_s_max": 80,
    "white_v_min": 200,
    "zone_row_fraction": 0.20,
    "tick_row_fraction": 0.08,
}


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.armed = False
        self.debug = False
        self.calibrate_requested = False
        self.quit_requested = False

    def snapshot(self) -> tuple[bool, bool, bool, bool]:
        with self.lock:
            return self.armed, self.debug, self.calibrate_requested, self.quit_requested

    def toggle_armed(self) -> bool:
        with self.lock:
            self.armed = not self.armed
            return self.armed

    def set_armed(self, value: bool) -> None:
        with self.lock:
            self.armed = value

    def toggle_debug(self) -> bool:
        with self.lock:
            self.debug = not self.debug
            return self.debug

    def request_calibration(self) -> None:
        with self.lock:
            self.calibrate_requested = True
            self.armed = False

    def take_calibration_request(self) -> bool:
        with self.lock:
            value = self.calibrate_requested
            self.calibrate_requested = False
            return value

    def request_quit(self) -> None:
        with self.lock:
            self.quit_requested = True
            self.armed = False


def load_config() -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] couldn't read {CONFIG_PATH}: {exc}; using defaults")
    else:
        save_config(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def vision_config(config: dict[str, Any]) -> VisionConfig:
    keys = VisionConfig.__dataclass_fields__.keys()
    return VisionConfig(**{key: config[key] for key in keys if key in config})


def calibrate_gauge(sct: mss.mss, config: dict[str, Any]) -> bool:
    """Let the user mark the full moving meter on a captured desktop image."""
    monitor = sct.monitors[1]
    desktop = np.asarray(sct.grab(monitor))[:, :, :3]
    height, width = desktop.shape[:2]
    scale = min(1.0, 1500.0 / width, 850.0 / height)
    preview = cv2.resize(desktop, (max(1, int(width * scale)), max(1, int(height * scale))))
    print("[calibration] drag a rectangle around the FULL Fish Fight gauge, then press Enter.")
    print("[calibration] include the moving white tick and the green zone at every height; exclude text/buttons.")
    selected = cv2.selectROI("Calibrate Fish Fight gauge - select the track", preview,
                             showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Calibrate Fish Fight gauge - select the track")
    x, y, w, h = [int(v) for v in selected]
    if w < 12 or h < 40:
        print("[calibration] cancelled or selection too small; old calibration kept.")
        return False
    left = monitor["left"] + int(round(x / scale))
    top = monitor["top"] + int(round(y / scale))
    config["roi"] = {"left": left, "top": top, "width": int(round(w / scale)), "height": int(round(h / scale))}
    save_config(config)
    print(f"[calibration] saved gauge ROI: {config['roi']}")
    return True


def roblox_has_focus() -> bool:
    """Return true only when the active window title identifies Roblox."""
    try:
        import pygetwindow
        active = pygetwindow.getActiveWindow()
        title = (active.title if active else "") or ""
        return "roblox" in title.lower()
    except Exception:
        return False


def start_hotkeys(state: AppState) -> keyboard.Listener:
    def on_press(key: keyboard.Key | keyboard.KeyCode | None):
        if key == keyboard.Key.f6:
            state.request_calibration()
            print("[hotkey] F6: calibration requested; macro disarmed")
        elif key == keyboard.Key.f7:
            armed = state.toggle_armed()
            print(f"[hotkey] F7: {'ARMED' if armed else 'DISARMED'}")
        elif key == keyboard.Key.f8:
            debug = state.toggle_debug()
            print(f"[hotkey] F8: detector preview {'on' if debug else 'off'}")
        elif key == keyboard.Key.esc:
            state.set_armed(False)
            print("[hotkey] Esc: disarmed")
        elif key == keyboard.Key.f9:
            state.request_quit()
            print("[hotkey] F9: exiting")
            return False
        return None

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener


def main() -> int:
    print("Sharkman Master Fish Fight Macro")
    print("F6 calibrate | F7 arm/disarm | F8 preview | Esc disarm | F9 exit")
    config = load_config()
    state = AppState()
    listener = start_hotkeys(state)
    history = MotionHistory()
    consumed_this_turn = False
    miss_count = 0
    was_visible = False
    last_focus_warning = 0.0
    last_debug_time = 0.0
    last_printed_status: str | None = None
    poll_hz = max(20, min(180, int(config.get("poll_hz", 90))))
    loop_period = 1.0 / poll_hz
    vision = vision_config(config)
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0

    try:
        with mss.mss() as sct:
            while True:
                loop_start = time.perf_counter()
                armed, debug, _, quitting = state.snapshot()
                if quitting:
                    break
                if state.take_calibration_request():
                    if calibrate_gauge(sct, config):
                        history.clear()
                        consumed_this_turn = False
                        miss_count = 0
                        vision = vision_config(config)
                    continue

                roi = config.get("roi")
                if not isinstance(roi, dict):
                    if last_printed_status != "uncalibrated":
                        print("[setup] no gauge ROI yet. Start the Fish Fight gauge and press F6 to calibrate.")
                        last_printed_status = "uncalibrated"
                    time.sleep(0.1)
                    continue

                try:
                    shot = sct.grab({key: int(roi[key]) for key in ("left", "top", "width", "height")})
                    crop = np.asarray(shot)[:, :, :3]
                    reading = detect_gauge(crop, vision)
                except Exception as exc:  # noqa: BLE001 - screen APIs can raise platform-specific exceptions
                    print(f"[screen] capture failed: {exc}; press F6 to recalibrate")
                    state.set_armed(False)
                    time.sleep(0.25)
                    continue

                now = time.perf_counter()
                if reading is None:
                    miss_count += 1
                    if was_visible and miss_count >= 5:
                        print("[gauge] gauge cleared; ready for the next player turn")
                        consumed_this_turn = False
                        history.clear()
                        was_visible = False
                    if debug and now - last_debug_time > 0.05:
                        cv2.imshow("Fish Fight detector preview", draw_diagnostics(crop, None))
                        cv2.waitKey(1)
                        last_debug_time = now
                else:
                    miss_count = 0
                    if not was_visible:
                        print("[gauge] detected the Fish Fight meter")
                        last_printed_status = None
                    was_visible = True
                    history.add(now, reading)
                    if debug and now - last_debug_time > 0.025:
                        cv2.imshow("Fish Fight detector preview", draw_diagnostics(crop, reading))
                        cv2.waitKey(1)
                        last_debug_time = now

                    if armed and not consumed_this_turn:
                        eta = time_to_alignment(
                            reading,
                            history,
                            horizon_s=float(config.get("prediction_horizon_s", 0.45)),
                        )
                        lead_window = max(0.012, min(0.045, float(config.get("press_lead_s", 0.020))))
                        if eta is not None and eta <= lead_window:
                            if not roblox_has_focus():
                                if now - last_focus_warning > 2.0:
                                    print("[safety] Roblox isn't the active window; no click sent. Focus Roblox before arming.")
                                    last_focus_warning = now
                            elif bool(config.get("dry_run", True)):
                                print(f"[dry-run] would press Space in {eta * 1000:.1f} ms (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f})")
                                consumed_this_turn = True
                            else:
                                try:
                                    pyautogui.click()
                                    x, y = pyautogui.position()
                                    print(f"[input] left-click sent at cursor ({x}, {y}; tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f}, eta={eta * 1000:.1f} ms)")
                                    consumed_this_turn = True
                                except pyautogui.FailSafeException:
                                    state.set_armed(False)
                                    print("[safety] PyAutoGUI fail-safe triggered; macro disarmed.")
                                except Exception as exc:
                                    state.set_armed(False)
                                    print(f"[safety] input failed; macro disarmed: {exc}")

                elapsed = time.perf_counter() - loop_start
                if elapsed < loop_period:
                    time.sleep(loop_period - elapsed)
    except KeyboardInterrupt:
        print("\n[exit] interrupted")
    finally:
        state.set_armed(False)
        listener.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
