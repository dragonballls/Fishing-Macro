# Issue #38: NPC root menu confirmation

Issue: https://github.com/KlisDev/Fishing-Macro/issues/38

The original supplied recording shows the Fisherman root menu opening. The
reporter's logs then stop startup because four settled action rows could not
be confirmed. That path can fail before a Nevermind click is attempted;
click coordinates alone do not prove an input-permission problem.

## Confirmed code defects

The dark-panel detector returned immediately when it found any two panels.
Translucent menus over dock/water scenery could merge lower panels or split
bands, hiding a clearly visible four-row label stack from the label detector.
Bright water outside the fading panel also joined labels into long white bands.
A pointer over Nevermind could extend the final white band just beyond its old
height limit. Exact comparison of text-pixel centres additionally treated small
backdrop/compression changes as continuing menu animation.

## Correction

- Compare both panel and label stacks; prefer a fuller, regularly spaced label
  stack over an incomplete panel result.
- Restrict label white to nearby dark backing, enclosed horizontally by dark
  pixels on the same scanline. Bright sky/water alone is not label evidence.
- Keep each label's pixels near the stack's common horizontal column, ignoring
  stray bright scenery between real rows before checking regular spacing.
- Allow the modest height extension caused by the pointer over the final label.
- Accept up to 8 horizontal / 3 vertical pixels of centre jitter against a fixed
  baseline. Count changes and larger/accumulating movement reset the settle timer.
- Reject unrelated highlights on opposite sides of the calibrated envelope.
- Keep the four-row root requirement, existing settle time, calibrated envelope,
  no-movement boundary for visible dialogue, and Shift Lock verification.
- Report expected and observed row counts after a page-confirmation timeout.

The change is shared by Windows and Linux/Sober. It does not migrate user config
or expand the saved menu area. A cropped-out Shop or Nevermind still requires
the user to correct calibration; it is not safe to infer a missing action row.

## Video replay evidence

The source is the user's 1280×720 recording, not a raw detector capture.
For replay, the image was scaled 1.5× to match the 1920×1080 recorded desktop.
The test envelope was explicitly set to include all four visible rows; the
reporter's actual saved config was unavailable.

| Segment | Frames | Committed detector | Patched detector |
| --- | ---: | --- | --- |
| 135–150 seconds | 450 | 447 two-row, 3 three-row detections | 450 four-row detections |
| 215–228 seconds | 390 | 390 rejected stacks | 390 four-row detections |

The real `wait_for_menu_page` function, driven by those recorded frames and a
simulated clock, confirmed root in 0.72 seconds in each segment. No input was
sent to Roblox. Synthetic regressions cover merged panels, bright background
rejection, pointer overlap, centre jitter, partial pages, and continuing motion.
The real `open_npc_dialogue` startup path also confirmed both recorded segments
in 0.72 seconds using fake input devices, with zero movement taps or Interact
clicks because the menu was already visible. Another 420 frames from closed-menu
segments (170–175 and 194–203 seconds) produced no accepted action stack.

The automated suite ran 109 tests: 104 passed and 5 opt-in GUI tests were skipped.
These include the existing Windows engine and mocked Linux platform regressions.
`git diff --check` passed. This patch changes detection/confirmation rather than
GUI layout, so the graphical resize tests were not required for this check.

This establishes a detector defect and verifies the patch on recorded evidence.
It does not establish whether every earlier issue #38 report has this cause,
or verify live clicking, purchases, sales, Shift Lock, or Linux window-manager
behavior. The reporter should retry the new version with their full menu area
and attach F8 logs if a later stage still fails.

Local extracted frames are diagnostic artifacts in an ignored `diag/` folder.
The user's recording and personal screenshots are not added to version control.

## Follow-up: optional color sampling selected obsolete UI logic

The reporter retried 1.8.1.1.42 and supplied the new recording
`_4heGooPflo` and their config on 2026-10-05. This is a separate residual
defect, not proof that the previous panel/label correction was unnecessary.
The new log sometimes confirms the root page, then reports that the NPC
dialogue could not close. The optional catch-dialogue color sample is off.

`_uses_update30_popup_detector()` incorrectly used `cap_dialogue_on` as a
current/old UI selector. With the sample off, menu counting, page signatures,
dialogue presence, dialogue exit and catch-card presence could use pre-Update
30 grey-band/blue-panel detection. After a real Nevermind dismissal, flooring
and scenery could therefore keep the macro in a phantom dialogue. Enabling
an optional sample happened to suppress those fallbacks; it was not a proper
requirement for current UI detection.

### Targeted correction in 1.8.1.1.43

- Use current live action rows for menu counts, page proofs, dialogue presence
  and exit on both supported runtimes, regardless of optional color sampling.
- Keep current yellow-header catch-card detection active with the sample off;
  a sample only supplements color matching. Do not fall back to the obsolete
  blue card when current detection says there is no catch popup.
- Preserve the four-row root proof, existing settle time and jitter tolerance,
  calibrated menu envelope, named buy/sell actions, bounded movement probes,
  no movement through visible dialogue and verified fishing Shift Lock.
- Keep saved config values and every calibration point. No migration, config
  reset, wider search rectangle or mandatory optional sample is needed.

### Exact-profile reproduction and limits

The reporter's saved envelope is left `0.692`, top `0.4384`, right `0.9048`,
bottom `0.7515`. With the logged game rectangle `1922x1022 at (-1,-1)`, it
projects to `(1329,447,409,320)`. Replay scales the supplied 1280x720 video
to its recorded 1920x1080 desktop; this remains compressed video evidence,
not the raw pixels returned by their capture backend.

In the new recording's closed-menu frame at 202 seconds, current action-row
detection correctly returns zero rows, but the obsolete counter returns two.
The pre-patch default profile therefore calls that scene an open dialogue.
The same defect is reproduced independently with synthetic grey scenery.
Open-menu segments contain complete stable four-row runs, so lowering the
required row count or loosening settling is not justified.

Recorded open/closed images plus the exact saved envelope drive the real root
confirmation, exit and full NPC-anchor functions using a simulated clock and
fake input devices. The patched path confirms root, sends one live Nevermind
click at `(1473,730)`, verifies the closed scene and completes the anchor with
both optional-sample settings. It sends no Interact click or movement key.
Shift Lock activation in that replay is mocked; separate existing tests cover
its verification and rejection safeguards.

Nine new synthetic tests run both optional-sample settings. Five fail against
the pre-patch default profile and pass after the correction. They cover closed
scenery, absence of obsolete detection, complete/partial root pages, real yellow
catch cards, old blue scenery, NPC name-strip suppression, one-click exit and
startup anchoring. Reporter media and config are not committed.

Final validation ran all 147 tests successfully with the opt-in GUI tests
enabled, including Windows regressions and mocked Linux platform coverage.
`git diff --check` passed. An independent code review found no blocking issues.

This fixes a confirmed default-profile defect. Live Roblox input acceptance,
the reporter's capture backend and live Sober/X11 behavior still require a
retry; recorded/mock tests are not a guarantee that every NPC failure is fixed.
