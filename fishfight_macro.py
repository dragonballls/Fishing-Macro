"""Screen-based helper for the Blox Fruits Sharkman Master Fish Fight.

Hotkeys:
  F6  Calibrate the gauge rectangle
  F7  Arm/disarm timed Spacebar presses (starts disarmed)
  F8  Toggle the visual detector preview
  Esc Disarm immediately
  F9  Exit

Only visible pixels and a standard Spacebar input event are used.
No client injection, remote calls, memory reading, or game-file modification.
"""
from __future__ import annotations

import threading
import time

import cv2
import mss
import numpy as np
from pynput import keyboard

from fishfight.timing import MotionHistory, time_to_alignment
from fishfight.vision import detect_gauge, draw_diagnostics
from fishfight.input_events import spacebar_down, spacebar_up
from fishfight.input_gate import InputOutcome, send_input_if_armed
from fishfight.settings import CONFIG_PATH, load_config, save_config, vision_config


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


def calibrate_gauge(sct: mss.MSS, config: dict[str, Any]) -> bool:
    """Let the user mark the full moving meter on the virtual desktop."""
    monitor = sct.monitors[0]
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
    held_hotkeys: set[keyboard.Key | keyboard.KeyCode] = set()

    def on_press(key: keyboard.Key | keyboard.KeyCode | None):
        if key not in {
            keyboard.Key.f6, keyboard.Key.f7, keyboard.Key.f8,
            keyboard.Key.esc, keyboard.Key.f9,
        }:
            return None
        if key in held_hotkeys:
            return None
        held_hotkeys.add(key)
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

    def on_release(key: keyboard.Key | keyboard.KeyCode | None):
        held_hotkeys.discard(key)
        return None

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    return listener


def main() -> int:
    print("Sharkman Master Fish Fight Macro")
    print("F6 calibrate | F7 arm/disarm (Spacebar) | F8 preview | Esc disarm | F9 exit")
    config = load_config()
    state = AppState()
    listener: keyboard.Listener | None = None
    history = MotionHistory()
    consumed_this_turn = False
    holding_spacebar = False
    hold_started_at = 0.0
    hold_start_window_s = 0.16
    max_spacebar_hold_s = 0.75
    miss_count = 0
    was_visible = False
    last_focus_warning = 0.0
    last_debug_time = 0.0
    last_capture_warning = -1e9
    last_printed_status: str | None = None
    poll_hz = max(20, min(180, int(config.get("poll_hz", 90))))
    loop_period = 1.0 / poll_hz
    vision = vision_config(config)

    try:
        listener = start_hotkeys(state)
        with mss.MSS() as sct:
            while True:
                loop_start = time.perf_counter()
                armed, debug, _, quitting = state.snapshot()
                if quitting:
                    break

                # A held key must be released on disarm, focus loss, or stalled prediction.
                if holding_spacebar:
                    focus_ok = bool(armed and roblox_has_focus())
                    timed_out = time.perf_counter() - hold_started_at >= max_spacebar_hold_s
                    if not armed or not focus_ok or timed_out:
                        try:
                            with state.lock:
                                spacebar_up()
                                if state.armed and (not focus_ok or timed_out):
                                    state.armed = False
                        except Exception as exc:
                            print(f"[safety] Spacebar release failed during cleanup: {exc}")
                        finally:
                            holding_spacebar = False
                        if armed and not focus_ok and time.perf_counter() - last_focus_warning > 2.0:
                            print("[safety] Roblox lost focus; Spacebar released and macro disarmed.")
                            last_focus_warning = time.perf_counter()
                        elif timed_out:
                            print("[safety] Alignment was not confirmed within the hold limit; Spacebar released and macro disarmed.")
                        armed = False

                if state.take_calibration_request():
                    if calibrate_gauge(sct, config):
                        history.clear()
                        was_visible = False
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
                    bounds = {key: roi[key] for key in ("left", "top", "width", "height")}
                    desktop = sct.monitors[0]
                    if (
                        bounds["left"] < desktop["left"]
                        or bounds["top"] < desktop["top"]
                        or bounds["left"] + bounds["width"] > desktop["left"] + desktop["width"]
                        or bounds["top"] + bounds["height"] > desktop["top"] + desktop["height"]
                    ):
                        config["roi"] = None
                        config["dry_run"] = True
                        state.set_armed(False)
                        history.clear()
                        was_visible = False
                        consumed_this_turn = False
                        save_config(config)
                        print("[config] saved ROI is outside the virtual desktop; dry_run reset to true; press F6 to recalibrate")
                        continue
                    shot = sct.grab(bounds)
                    crop = np.asarray(shot)[:, :, :3]
                    reading = detect_gauge(crop, vision)
                except Exception as exc:  # noqa: BLE001 - screen APIs can raise platform-specific exceptions
                    state.set_armed(False)
                    history.clear()
                    was_visible = False
                    miss_count = 0
                    # Keep consumed_this_turn unchanged: a capture failure after a
                    # successful click must not permit a duplicate click this turn.
                    warning_time = time.perf_counter()
                    if warning_time - last_capture_warning >= 2.0:
                        print(f"[screen] capture failed: {exc}; press F6 to recalibrate")
                        last_capture_warning = warning_time
                    time.sleep(0.1)
                    continue

                now = time.perf_counter()
                if reading is None:
                    miss_count += 1
                    if was_visible and miss_count >= 5:
                        if holding_spacebar:
                            try:
                                with state.lock:
                                    spacebar_up()
                            except Exception as exc:
                                print(f"[safety] Spacebar release failed after gauge cleared: {exc}")
                            finally:
                                holding_spacebar = False
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

                    if armed and not consumed_this_turn and state.snapshot()[0]:
                        eta = time_to_alignment(
                            reading,
                            history,
                            horizon_s=config["prediction_horizon_s"],
                        )
                        lead_window = config["press_lead_s"]

                        if config["dry_run"]:
                            # Report the hold/release action without sending input.
                            if eta is not None and eta <= hold_start_window_s:
                                with state.lock:
                                    still_armed = state.armed
                                    lost_focus = still_armed and not roblox_has_focus()
                                    if lost_focus:
                                        state.armed = False
                                if lost_focus:
                                    if now - last_focus_warning > 2.0:
                                        print("[safety] Roblox is not the active window; macro disarmed and no input sent.")
                                        last_focus_warning = now
                                elif still_armed:
                                    print(f"[dry-run] would hold Spacebar, then release in about {max(0.0, eta) * 1000:.1f} ms (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f})")
                                    consumed_this_turn = True
                        else:
                            try:
                                if not holding_spacebar and eta is not None and eta <= hold_start_window_s:
                                    outcome = send_input_if_armed(state, roblox_has_focus, spacebar_down)
                                    if outcome is InputOutcome.FOCUS_LOST:
                                        if now - last_focus_warning > 2.0:
                                            print("[safety] Roblox is not the active window; macro disarmed and no input sent.")
                                            last_focus_warning = now
                                    elif outcome is InputOutcome.SENT:
                                        holding_spacebar = True
                                        hold_started_at = time.perf_counter()
                                        print(f"[input] Spacebar down; predicted alignment in {max(0.0, eta) * 1000:.1f} ms")
                                        # If already at the target, leave a small down interval so both edges register.
                                        if eta <= lead_window:
                                            time.sleep(0.004)
                                            with state.lock:
                                                spacebar_up()
                                            holding_spacebar = False
                                            consumed_this_turn = True
                                            print(f"[input] Spacebar up at alignment (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f})")
                                elif holding_spacebar and eta is not None and eta <= lead_window:
                                    # Key-up is safety-critical: always attempt it once a target is reached.
                                    with state.lock:
                                        spacebar_up()
                                    holding_spacebar = False
                                    consumed_this_turn = True
                                    print(f"[input] Spacebar up at alignment (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f}, eta={eta * 1000:.1f} ms)")
                            except Exception as exc:
                                if holding_spacebar:
                                    try:
                                        spacebar_up()
                                    except Exception:
                                        pass
                                    holding_spacebar = False
                                state.set_armed(False)
                                print(f"[safety] input failed; macro disarmed: {exc}")

                elapsed = time.perf_counter() - loop_start
                if elapsed < loop_period:
                    time.sleep(loop_period - elapsed)
    except KeyboardInterrupt:
        print("\n[exit] interrupted")
    finally:
        state.set_armed(False)
        if holding_spacebar:
            try:
                spacebar_up()
                print("[safety] Spacebar released during shutdown.")
            except Exception as exc:
                print(f"[safety] Spacebar release failed during shutdown: {exc}")
            holding_spacebar = False
        if listener is not None:
            listener.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
