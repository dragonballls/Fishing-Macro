# Windows and Linux parity for 1.8.1.1.41

## Shared features

Linux's GUI launcher configures its profile and Sober/X11 backends before
importing `WINDOWS/easy_run.py`. Both platforms use the same Setup, Calibration,
Preparation Guide, and Run Console, including read-only screenshot/reference
zoom, responsive layout, session review counters, and the native calibration
canvas correction for CustomTkinter 5.2.2.

Both launchers use the shared engine, shop, vision, routes, and config version.
The NPC menu confirmation repair, Shift Lock verification/startup recovery,
fish-only behavior, watchdog, fishing loop, purchases, and sales therefore use
one implementation. Linux retains its X11/uinput input and focus backends and
click-through F8 overlay. Wayland support is not added.

Linux config, assets, templates, logs, diagnostic captures, and recordings remain
isolated from Windows. Keep both source folders when distributing the project.

## Terminal gap corrected

The former Linux terminal runner constructed an engine but never collected its
starting bait count. That counter always stayed `None`, disabling automatic
buying even when the saved NPC route selected Fisherman.

`bloxfish/terminal_setup.py` now owns the setup questions for both platforms:
NPC or fish-only mode, purchase amount, rod slot, sell interval, starting bait
count, and readiness confirmation. It imports no OS backend or dependency
installer and does not write calibration/configuration or send game input.
Windows retains its launcher helper hooks; Linux uses the same setup directly.

`--now` skips only the hotkey wait after setup, as on Windows. Previously Linux
started without these questions, so scripts using Linux `--now` must now supply
setup answers or use the GUI. EOF/cancellation does not start a worker.

Canceled Linux setup closes the engine and any development log. Terminal
shutdown now gives an active worker the same three-second join interval as
Windows before closing devices. F2 starts/stops, F4 quits, and terminal F8
remains log-only. GUI F4 still stops without closing the app.

## Validation and limits

- Fresh-process Linux-context import confirms the current shared GUI/core,
  shared version, Linux assets, and Linux config path.
- Linux launcher tests use real setup questions with mocked devices/workers:
  tracked bait activates buying, fish-only stays independent of NPC actions,
  blank tracking plus selling disabled uses manual fishing, and cancellation
  never starts input or hotkeys.
- Development output stays beside the selected Linux config; cancellation
  closes its log. Active-worker shutdown requests stop and joins the worker.
- The full regression suite includes Windows/GUI tests and mocked Linux
  preflight, input, focus, runtime-path, overlay, and route checks.
- Final run: all 138 tests passed with real GUI tests enabled.
  `git diff --check` passed; user config and runtime captures remain ignored.

No live Sober/X11 gameplay is available on the Windows test host. Automated
parity checks are not a guarantee of compatibility with every Sober release,
desktop environment, or window manager. Live capture, hotkeys, buying, selling,
and hitbox acceptance still require a Linux/Sober session.
