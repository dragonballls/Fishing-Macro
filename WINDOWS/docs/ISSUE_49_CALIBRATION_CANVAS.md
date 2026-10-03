# Issue #49: calibration hover and drag crash

Report: https://github.com/KlisDev/Fishing-Macro/issues/49

The reporter identifies macro 1.8.1.1.39 and confirms the same error on
1.8.1.1.40, meeting the supported issue-review version cutoff.

## Confirmed cause

Calibration used `customtkinter.CTkCanvas` as its editable screenshot canvas.
CustomTkinter's released v5.2.2 implementation of `coords()` calls the native
Tk method but does not return its result. Reading a rectangle or oval therefore
returns `None`, even though the item exists. Hover, press, move, and commit
expect four coordinates and cannot work with that return value.

This is not evidence of bad calibration, a missing screenshot, or a Python
3.13-specific failure. Do not ask users to delete config.json to resolve it.

Sources:

- https://github.com/TomSchimansky/CustomTkinter/blob/v5.2.2/customtkinter/windows/widgets/core_rendering/ctk_canvas.py
- https://github.com/TomSchimansky/CustomTkinter/discussions/2410

The bundled test runtime has CustomTkinter 6.0.0, whose `coords()` does return
coordinates. Tests only on that runtime missed the released-library behavior.

## Targeted repair

- Use public `tkinter.Canvas` for the calibration screenshot and editable
  overlays. Keep the dark surface, bindings, geometry, and normalization.
- Leave CustomTkinter's own component-rendering canvases alone. No installed
  package is patched and no dependency upgrade is required.
- Cancel an in-flight drag whenever redraw replaces its items. Its old pixel
  anchor must not move a newly selected control or a resized screenshot.
- Preserve all config fields, saved controls, review rules, optional color
  capture, reference images, and read-only zoom.
- Linux's launcher imports this same Calibrator, so the repair applies to both
  supported platforms without copying the GUI.

## Regression checks

`test_image_inspector.py` adds real-Tk tests that:

1. Reproduce the exact `NoneType` hover and press failures using an internal
   canvas with v5.2.2 return behavior.
2. Generate hover, press, motion, and release events for all calibration regions
   and click points at 900x520, 1000x680, and 1440x900.
3. Resize every region using its grip; verify updated normalized coordinates,
   engine-equivalent projected outlines, review marking, and config reload.
4. Resize the window or change selection during a drag; confirm an old motion
   cannot change either control's saved values.

Existing tests also exercise Re-shoot, screenshot/reference zoom, scrolling,
review preservation, optional samples, close cleanup, DPI-coordinate conversion,
the Windows engine, and mocked Linux platform behavior.

The full suite passes all 132 tests with GUI tests enabled on the Windows test
desktop. It was run both with the actual CustomTkinter 5.2.2 package installed
in an isolated temporary directory and with the bundled CustomTkinter 6.0.0.
The compatibility tests retain v5.2.2 return semantics on either library so a
newer test environment cannot mask this defect again. `git diff --check` passes.

All captures and game-window lookups in UI tests are synthetic or mocked. No
input is sent to Roblox or Sober, and the user's configuration is not written.
Live Sober/X11 acceptance still requires a Linux machine.
