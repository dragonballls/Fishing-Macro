# Issue 48: real fish-only mode

Report: https://github.com/KlisDev/Fishing-Macro/issues/48

The report asks for fishing without compulsory NPC positioning or Shift Lock
tests. The requested behavior was reproduced from the current code, rather than
assuming an older build's Linux report establishes a current platform defect.

## Confirmed paths

- Startup called `establish_fishing_anchor()` whenever
  `shop.enter_stance_on_start` was true, even with `shop.npc = "none"`.
- Disabling that legacy startup setting still called `enter_fishing_stance()`.
- Every cast demanded Shift Lock verification regardless of NPC settings.
- `_needs_bait()` tested only the software counter. A disabled shop therefore
  still got a purchase request when bait reached the threshold.
- Failed casts unconditionally tried NPC dialogue recovery.
- Setup/Preparation instructed every user to start beside the Fisherman.

## Routing contract

`bloxfish/routes.py` provides side-effect-free checks shared by the GUI, engine,
and Windows terminal runner. Linux imports the same engine/GUI implementation.

| Settings | Result |
| --- | --- |
| Don't buy / `shop.npc` = `none`, `off`, or empty | Fish-only; no buying or selling, regardless of saved counts/intervals |
| Fisherman; bait count blank; selling disabled or interval 0 | Fish-only |
| Fisherman; tracked bait; positive purchase amount; attempts available | Buying enabled; NPC safeguards retained |
| Fisherman; selling enabled with positive interval | Selling enabled, even if buying/tracking is off; NPC safeguards retained |
| Non-positive purchase amount or purchase-failure limit reached | Buying disabled; an independently enabled sale route remains active |

Fish-only skips the anchor, dialogue detection/recovery, movement, and Shift Lock
toggles/tests, including pre-cast verification. It uses the user's position and
cursor/lock setup. Low bait cannot schedule a disabled purchase. The normal cast,
bite, reel, rod-flick, chest, minigame-presence, hotkey, and watchdog paths remain.

Preparation previews pending Setup answers without saving them. No-NPC guidance
replaces mandatory NPC/Shift Lock instructions and does not create the NPC
simulation. Back/Finish preserve the pending mode. Saved sell intervals and
calibration are not erased, and no config schema migration is required.

A detected persistent recipe Learn note stops a fish-only run with instructions
to clear it manually and restore fishing aim before restarting. The user's
Shift Lock state is unknown in this mode, so automatically toggling it to click
Learn would violate the no-toggle contract. Ordinary catch handling remains.

## Validation

- Mocked Windows and Sober startup/restart: no NPC helpers, keyboard taps, cursor
  queries, movement, menu clicks, or NPC captures in fish-only startup.
- Cursor-read errors and failed casts do not activate NPC or Shift Lock recovery.
- Low/zero bait, blank tracking, zero purchase amount, failure limits, and
  preserved selling settings exercise the routing policy.
- A full simulated cast/bite/reel/catch cycle continues without a shop call.
- Buying-only and selling-only preserve anchor failure protection.
- Live minigame detection and the no-response watchdog still prevent unsafe casts
  or release held input; recipe-note handling stops without a blind toggle.
- Config save/reload preserves the no-buy choice and calibration.
- Terminal prompts still request the rod slot and show manual preparation.
- Real Tk windows: 780x560, 1080x740, 1440x900; mode-specific summaries/guides,
  repeated expand/collapse, Back, and Finish. Capture/input backends were mocked.
- Preparation text wraps to available logical width. Updates are debounced,
  coalesced, and canceled on destruction, with no permanent idle redraw loop.
- UI screenshots are local ignored files in `WINDOWS/diag/issue48-review/`.
- Final full suite: **129 tests passed**, including all six opt-in real Tk
  tests and the Windows/Linux platform regressions. `git diff --check` passed.

No live Roblox or Sober gameplay was available. Automated checks establish the
code paths and UI behavior, not live fishing reliability on every setup.
