# Sharkman Master Fish Fight Macro

A fresh Windows-first screen macro aimed specifically at the Fish Fight gauge used by the Sharkman Master Headband challenge in Blox Fruits. This is not a fishing macro.

It watches the visible moving tick and green target zone inside a gauge area you calibrate, predicts short-term alignment, and (when armed) sends one normal left-click at the current mouse cursor position for the current player turn. It does not move the cursor. The tool only reads desktop pixels and sends standard mouse input; it does not inject into Roblox, read process memory, call game remotes, or modify game files.

> **Important limitation:** This is a new implementation based on the visible gauge mechanics, not a live-tested guarantee. The Black Headband stage has narrow timing windows and the game may apply network/server-side success rules. Test with dry-run and lower stages first. A screen macro cannot promise a win or prevent game-side failure.

## Setup (Windows)

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Download this repository as a ZIP and extract it.
3. Open PowerShell in the extracted folder and run:

        py -3.12 -m venv .venv
        .\.venv\Scripts\python -m pip install --upgrade pip
        .\.venv\Scripts\python -m pip install -r requirements.txt
        .\.venv\Scripts\python fishfight_macro.py

4. Start the Sharkman Master Fish Fight manually. When the gauge is visible, press **F6** and drag a rectangle tightly around the full moving meter track. Include both the green target band and the moving white tick; leave out other text, health bars, and buttons. Press Enter to save. Calibration is written to local config.json and is not committed.
5. Leave **dry_run** set to **true** initially. Press **F8** to show the detector preview, then **F7** to arm. In dry-run mode it logs when it would click but does not send input. Verify the white line tracks the moving tick and the green rectangle overlays the target zone. Press Esc to disarm.
6. When detection looks correct, close the app, change the dry_run setting from true to false in config.json, restart it, and explicitly press F7 to arm. The click occurs at the cursor's current position. Keep Roblox focused and place the cursor where the action should register. Use automation only where the game rules permit it.

## Hotkeys

| Key | Action |
|---|---|
| **F6** | Disarm and calibrate the gauge rectangle |
| **F7** | Arm/disarm; starts disarmed every launch |
| **F8** | Show/hide the visual detector preview |
| **Esc** | Immediately disarm |
| **F9** | Exit the app |

The app only left-clicks at the current cursor position when all of these are true: (1) the gauge has a credible green band and white tick, (2) enough recent frames exist to estimate movement, (3) a predicted near-term alignment is inside the central portion of the green band, (4) the app is armed, and (5) a Roblox-titled window is active. It sends no more than one left-click per detected gauge; the gauge must disappear before another turn can trigger.

## Configuration and tuning

config.json is created on first launch and is intentionally ignored by Git. You can adjust the HSV thresholds if green/white detection is wrong:

- **green_h_min**, **green_h_max**, **green_s_min**, **green_v_min**: green target-zone detection
- **white_s_max**, **white_v_min**: white tick detection
- **zone_row_fraction**, **tick_row_fraction**: minimum row coverage inside the calibrated crop
- **poll_hz**: screen polling rate (clamped to 20–180)
- **prediction_horizon_s**: short prediction horizon
- **press_lead_s**: how early a predicted alignment may trigger a click (clamped to 12–45 ms)
- **dry_run**: true logs without clicking; false sends a left-click at the current cursor when armed

If the preview misses the gauge or selects the wrong white feature, disarm, recalibrate more tightly, and adjust thresholds incrementally. The app disarms when a trigger is reached while Roblox is not the active window. Esc and F6 disarm immediately. Configuration is range/type checked; malformed ROIs require recalibration, and writes are atomic.

## Tests

Unit tests use synthetic images and known trajectories. They validate detector behavior and timing prediction, but cannot substitute for a live Roblox test or confirm a successful win. Run:

        python -m unittest discover -s tests -v

GitHub Actions compiles the Python files, runs the unit tests, and packages a source ZIP artifact.

## Safety and scope

- Starts disarmed and defaults to dry-run.
- Uses ordinary screen capture and a normal left-click at the current cursor position only.
- Does not automate accepting the quest, selecting fish, clicking Continue, or leaving/restarting a challenge; those remain manual.
- Does not read memory, inject code, change game files, or invoke Roblox remotes.
- Game rules may prohibit automation; use only if permitted by the game's rules.
