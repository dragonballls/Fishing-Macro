# Sharkman Master Fish Fight Macro

A fresh Windows-first screen macro aimed specifically at the Fish Fight gauge used by the Sharkman Master Headband challenge in Blox Fruits. This is not a fishing macro.

It watches the visible moving tick and green target zone inside a gauge area you calibrate, predicts short-term alignment, and holds then releases an input at alignment. Spacebar is the default action. If the game flow needs a specific on-screen click target, **F5 calibrates its screen location** and switches to a left-mouse hold/release action; **F4 switches back to Spacebar or to the calibrated mouse action**. On Windows it sends checked keyboard or mouse events through SendInput. It does not inject into Roblox, read process memory, call game remotes, or modify game files.

> **Important limitation:** This is a new implementation based on the visible gauge mechanics, not a live-tested guarantee. The Black Headband stage has narrow timing windows and the game may apply network/server-side success rules. Test with dry-run and lower stages first. A screen macro cannot promise a win or prevent game-side failure.

## Setup (Windows)

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Download this repository as a ZIP and extract it.
3. Open PowerShell in the extracted folder and run:

        py -3.12 -m venv .venv
        .\.venv\Scripts\python -m pip install --upgrade pip
        .\.venv\Scripts\python -m pip install -r requirements.txt
        .\.venv\Scripts\python fishfight_macro.py

4. Start the Sharkman Master Fish Fight manually. When the gauge is visible, press **F6** and drag a rectangle tightly around the full moving meter track. Include both the green target band and the moving white tick; leave out other text, health bars, and buttons. Press Enter to save. If the challenge needs a fixed on-screen click target, press **F5**, drag a rectangle around that target, and press Enter; the rectangle center is saved and mouse mode is selected automatically. Press **F4** to switch between Spacebar and calibrated mouse mode. Calibration is written to local config.json and is not committed.
5. Leave **dry_run** set to **true** initially. Press **F8** to show the detector preview and verify that the white line tracks the moving tick and the green rectangle overlays the target zone. Press **F8** again to close the preview, click Roblox to give it focus, and press **F7** to arm. In dry-run mode it logs when it would press Spacebar but sends no input. Press Esc to disarm.
6. When detection looks correct, close the app, change **dry_run** from true to false in config.json, and restart it. Keep Roblox focused, do not reopen the preview while armed, and explicitly press **F7** to arm. The macro starts holding Spacebar when alignment is predicted to be close, then releases it when the tick reaches the target window. If focus is lost or alignment is not confirmed quickly, it releases the key and disarms. Use automation only where the game rules permit it.

## Hotkeys

| Key | Action |
|---|---|
| **F4** | Switch between Spacebar and calibrated left-mouse action |
| **F5** | Disarm and calibrate the on-screen click target; selects mouse mode |
| **F6** | Disarm and calibrate the gauge rectangle |
| **F7** | Arm/disarm the selected timed action; starts disarmed every launch |
| **F8** | Show/hide the visual detector preview |
| **Esc** | Immediately disarm |
| **F9** | Exit the app |

The app starts holding the selected action when (1) the gauge has a credible green band and white tick, (2) enough recent frames exist to predict alignment within 160 ms, (3) the app is armed, and (4) a Roblox-titled window is active. It releases the selected action when the prediction enters the configured release window (12–45 ms). A held key or mouse button is released on focus loss, disarm, gauge clearance, shutdown, or after a 750 ms safety timeout. It performs at most one hold/release action per detected gauge; the gauge must disappear before another turn can trigger.

## Configuration and tuning

config.json is created on first launch and is intentionally ignored by Git. You can adjust the HSV thresholds if green/white detection is wrong:

- **green_h_min**, **green_h_max**, **green_s_min**, **green_v_min**: green target-zone detection
- **white_s_max**, **white_v_min**: white tick detection
- **zone_row_fraction**, **tick_row_fraction**: minimum row coverage inside the calibrated crop
- **poll_hz**: screen polling rate (clamped to 20–180)
- **prediction_horizon_s**: short prediction horizon
- **press_lead_s**: release window before predicted alignment (clamped to 12–45 ms; selected action begins when predicted alignment is within 160 ms)
- **input_mode**: "spacebar" or "mouse_click"; F4 switches modes
- **action_point**: the screen-coordinate center saved by F5; required for mouse_click mode
- **dry_run**: true logs the predicted hold/release without sending input; false holds and releases the selected action when armed

If the preview misses the gauge or selects the wrong white feature, disarm, recalibrate more tightly, and adjust thresholds incrementally. The app disarms when a trigger is reached while Roblox is not the active window. Esc and F6 disarm immediately. Configuration is range/type checked; malformed ROIs require recalibration, and writes are atomic.

## Tests

Unit tests use synthetic images and known trajectories. They validate detector behavior and timing prediction, but cannot substitute for a live Roblox test or confirm a successful win. Run:

        python -m unittest discover -s tests -v

GitHub Actions compiles the Python files, runs the unit tests, and packages a source ZIP artifact.

## Safety and scope

- Starts disarmed and defaults to dry-run.
- Uses ordinary screen capture and standard OS keyboard/mouse input only. On Windows, Spacebar uses scan codes and calibrated mouse input uses virtual-desktop coordinates; release is attempted during disarm, focus loss, timeout, gauge clearance, and shutdown.
- Does not automate accepting the quest, selecting fish, clicking Continue, or leaving/restarting a challenge; those remain manual.
- Does not read memory, inject code, change game files, or invoke Roblox remotes.
- Windows may reject synthetic input if Roblox is elevated and the macro is not (or vice versa); run both at the same privilege level if the log reports a rejected SendInput event. Game rules may prohibit automation; use only if permitted by the game's rules.
