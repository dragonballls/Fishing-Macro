"""Screen-based helper for the Blox Fruits Sharkman Master Fish Fight.

Hotkeys:
  F4  Switch Spacebar / calibrated left-mouse action
  F5  Calibrate the on-screen mouse action target
  F6  Calibrate the gauge rectangle
  F7  Arm/disarm the selected timed action (starts disarmed)
  F8  Toggle the visual detector preview
  Esc Disarm immediately
  F9  Exit

Uses visible pixels and ordinary OS keyboard/mouse input only. No client
injection, remote calls, memory reading, or game-file modification.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import mss
import numpy as np
from pynput import keyboard

from fishfight.timing import MotionHistory, time_to_alignment
from fishfight.vision import detect_gauge, draw_diagnostics
from fishfight.input_events import mouse_left_down, mouse_left_up, spacebar_down, spacebar_up
from fishfight.input_gate import InputOutcome, send_input_if_armed
from fishfight.settings import CONFIG_PATH, load_config, save_config, vision_config


class AppState:
    def __init__(self, input_mode: str = "spacebar") -> None:
        self.lock = threading.Lock()
        self.armed = False
        self.debug = False
        self.calibrate_gauge_requested = False
        self.calibrate_button_requested = False
        self.mode_toggle_requested = False
        self.quit_requested = False
        self.input_mode = input_mode

    def snapshot(self) -> tuple[bool, bool, bool, bool, bool, bool, str]:
        with self.lock:
            return (
                self.armed,
                self.debug,
                self.calibrate_gauge_requested,
                self.calibrate_button_requested,
                self.mode_toggle_requested,
                self.quit_requested,
                self.input_mode,
            )

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

    def request_gauge_calibration(self) -> None:
        with self.lock:
            self.calibrate_gauge_requested = True
            self.armed = False

    def take_gauge_calibration_request(self) -> bool:
        with self.lock:
            value = self.calibrate_gauge_requested
            self.calibrate_gauge_requested = False
            return value

    def request_button_calibration(self) -> None:
        with self.lock:
            self.calibrate_button_requested = True
            self.armed = False

    def take_button_calibration_request(self) -> bool:
        with self.lock:
            value = self.calibrate_button_requested
            self.calibrate_button_requested = False
            return value

    def request_mode_toggle(self) -> None:
        with self.lock:
            self.mode_toggle_requested = True
            self.armed = False

    def take_mode_toggle_request(self) -> bool:
        with self.lock:
            value = self.mode_toggle_requested
            self.mode_toggle_requested = False
            return value

    def set_input_mode(self, value: str) -> None:
        with self.lock:
            self.input_mode = value

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


def calibrate_action_button(sct: mss.MSS, config: dict[str, Any]) -> bool:
    """Let the user select the screen target for the left-mouse action."""
    monitor = sct.monitors[0]
    desktop = np.asarray(sct.grab(monitor))[:, :, :3]
    height, width = desktop.shape[:2]
    scale = min(1.0, 1500.0 / width, 850.0 / height)
    preview = cv2.resize(desktop, (max(1, int(width * scale)), max(1, int(height * scale))))
    title = "Calibrate Fish Fight action button - select target"
    print("[calibration] drag a rectangle over the exact on-screen target to click, then press Enter.")
    print("[calibration] this saves the rectangle center and switches the action to left mouse; press Esc to cancel.")
    selected = cv2.selectROI(title, preview, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    x, y, w, h = [int(v) for v in selected]
    if w < 3 or h < 3:
        print("[calibration] cancelled or selection too small; previous target kept.")
        return False
    point_x = monitor["left"] + int(round((x + w / 2) / scale))
    point_y = monitor["top"] + int(round((y + h / 2) / scale))
    config["action_point"] = {"x": point_x, "y": point_y}
    config["input_mode"] = "mouse_click"
    save_config(config)
    print(f"[calibration] saved left-mouse target at ({point_x}, {point_y}); input mode is mouse_click")
    return True


def action_label(mode: str) -> str:
    return "left mouse button at calibrated target" if mode == "mouse_click" else "Spacebar"


def action_down(mode: str, point: dict[str, int] | None) -> None:
    if mode == "spacebar":
        spacebar_down()
    elif mode == "mouse_click":
        if not isinstance(point, dict):
            raise RuntimeError("No mouse target is calibrated; press F5 before selecting mouse mode.")
        mouse_left_down(point["x"], point["y"])
    else:
        raise RuntimeError(f"Unsupported input mode: {mode!r}")


def action_up(mode: str | None, point: dict[str, int] | None) -> None:
    if mode == "spacebar":
        spacebar_up()
    elif mode == "mouse_click":
        if not isinstance(point, dict):
            raise RuntimeError("Cannot release the left mouse button: calibrated target is missing.")
        mouse_left_up(point["x"], point["y"])
    else:
        raise RuntimeError(f"Cannot release unsupported input mode: {mode!r}")


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
            keyboard.Key.f4, keyboard.Key.f5, keyboard.Key.f6,
            keyboard.Key.f7, keyboard.Key.f8, keyboard.Key.esc, keyboard.Key.f9,
        }:
            return None
        if key in held_hotkeys:
            return None
        held_hotkeys.add(key)
        if key == keyboard.Key.f4:
            state.request_mode_toggle()
            print("[hotkey] F4: input-mode switch requested; macro disarmed")
        elif key == keyboard.Key.f5:
            state.request_button_calibration()
            print("[hotkey] F5: click-target calibration requested; macro disarmed")
        elif key == keyboard.Key.f6:
            state.request_gauge_calibration()
            print("[hotkey] F6: gauge calibration requested; macro disarmed")
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
    print("F4 switch action | F5 calibrate click target | F6 calibrate gauge | F7 arm/disarm | F8 preview | Esc disarm | F9 exit")
    config = load_config()
    state = AppState(str(config.get("input_mode", "spacebar")))
    listener: keyboard.Listener | None = None
    history = MotionHistory()
    consumed_this_turn = False
    holding_action = False
    holding_mode: str | None = None
    holding_point: dict[str, int] | None = None
    hold_started_at = 0.0
    hold_start_window_s = 0.16
    max_action_hold_s = 0.75
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
                armed, debug, _, _, _, quitting, input_mode = state.snapshot()
                if quitting:
                    break

                # Any held action is released on disarm, focus loss, or stalled prediction.
                if holding_action:
                    focus_ok = bool(armed and roblox_has_focus())
                    timed_out = time.perf_counter() - hold_started_at >= max_action_hold_s
                    if not armed or not focus_ok or timed_out:
                        try:
                            with state.lock:
                                action_up(holding_mode, holding_point)
                                if state.armed and (not focus_ok or timed_out):
                                    state.armed = False
                        except Exception as exc:
                            print(f"[safety] {action_label(holding_mode or 'spacebar')} release failed during cleanup: {exc}")
                        finally:
                            holding_action = False
                            holding_mode = None
                            holding_point = None
                        if armed and not focus_ok and time.perf_counter() - last_focus_warning > 2.0:
                            print("[safety] Roblox lost focus; held action released and macro disarmed.")
                            last_focus_warning = time.perf_counter()
                        elif timed_out:
                            print("[safety] Alignment was not confirmed within the hold limit; held action released and macro disarmed.")
                        armed = False

                if state.take_mode_toggle_request():
                    missing_target = False
                    with state.lock:
                        if state.input_mode == "spacebar":
                            if isinstance(config.get("action_point"), dict):
                                state.input_mode = "mouse_click"
                            else:
                                missing_target = True
                                state.input_mode = "spacebar"
                        else:
                            state.input_mode = "spacebar"
                        input_mode = state.input_mode
                    config["input_mode"] = input_mode
                    save_config(config)
                    if missing_target:
                        print("[mode] no calibrated click target; press F5 first. Staying on Spacebar.")
                    else:
                        print(f"[mode] selected input action: {action_label(input_mode)}")

                if state.take_button_calibration_request():
                    if calibrate_action_button(sct, config):
                        state.set_input_mode("mouse_click")
                        history.clear()
                        was_visible = False
                        consumed_this_turn = False
                        miss_count = 0
                    continue

                if state.take_gauge_calibration_request():
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
                        if holding_action:
                            try:
                                with state.lock:
                                    action_up(holding_mode, holding_point)
                            except Exception as exc:
                                print(f"[safety] held action release failed after gauge cleared: {exc}")
                            finally:
                                holding_action = False
                                holding_mode = None
                                holding_point = None
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
                            # Report whichever calibrated action would be held/released, without sending input.
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
                                    print(f"[dry-run] would hold {action_label(input_mode)}, then release in about {max(0.0, eta) * 1000:.1f} ms (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f})")
                                    consumed_this_turn = True
                        else:
                            try:
                                point = config.get("action_point") if input_mode == "mouse_click" else None
                                if not holding_action and eta is not None and eta <= hold_start_window_s:
                                    outcome = send_input_if_armed(
                                        state,
                                        roblox_has_focus,
                                        lambda: action_down(input_mode, point),
                                    )
                                    if outcome is InputOutcome.FOCUS_LOST:
                                        if now - last_focus_warning > 2.0:
                                            print("[safety] Roblox is not the active window; macro disarmed and no input sent.")
                                            last_focus_warning = now
                                    elif outcome is InputOutcome.SENT:
                                        holding_action = True
                                        holding_mode = input_mode
                                        holding_point = dict(point) if isinstance(point, dict) else None
                                        hold_started_at = time.perf_counter()
                                        print(f"[input] {action_label(input_mode)} down; predicted alignment in {max(0.0, eta) * 1000:.1f} ms")
                                        # If already at the target, leave a small down interval so both edges register.
                                        if eta <= lead_window:
                                            time.sleep(0.004)
                                            with state.lock:
                                                action_up(holding_mode, holding_point)
                                            holding_action = False
                                            holding_mode = None
                                            holding_point = None
                                            consumed_this_turn = True
                                            print(f"[input] {action_label(input_mode)} up at alignment (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f})")
                                elif holding_action and eta is not None and eta <= lead_window:
                                    # Release the same action and target that were originally pressed.
                                    with state.lock:
                                        action_up(holding_mode, holding_point)
                                    released_label = action_label(holding_mode or "spacebar")
                                    holding_action = False
                                    holding_mode = None
                                    holding_point = None
                                    consumed_this_turn = True
                                    print(f"[input] {released_label} up at alignment (tick={reading.tick_y:.3f}, zone={reading.zone_center:.3f}, eta={eta * 1000:.1f} ms)")
                            except Exception as exc:
                                if holding_action:
                                    try:
                                        action_up(holding_mode, holding_point)
                                    except Exception:
                                        pass
                                    holding_action = False
                                    holding_mode = None
                                    holding_point = None
                                state.set_armed(False)
                                print(f"[safety] input failed; macro disarmed: {exc}")

                elapsed = time.perf_counter() - loop_start
                if elapsed < loop_period:
                    time.sleep(loop_period - elapsed)
    except KeyboardInterrupt:
        print("\n[exit] interrupted")
    finally:
        state.set_armed(False)
        if holding_action:
            try:
                action_up(holding_mode, holding_point)
                print(f"[safety] {action_label(holding_mode or 'spacebar')} released during shutdown.")
            except Exception as exc:
                print(f"[safety] held action release failed during shutdown: {exc}")
            holding_action = False
            holding_mode = None
            holding_point = None
        if listener is not None:
            listener.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
