# Fishing Macro

An auto-fisher for the Blox Fruits fishing minigame. It reads the screen, plays
the reel minigame, buys bait when it runs low, and sells the catch — driven by
what's on screen (colors and shapes), not fixed timings, so it adapts to
different rods, lighting and times of day.

**New here or stuck?** Download and extract the project, then open
**[GUIDE.html](GUIDE.html)** in your browser for installation, calibration,
searchable questions, and fixes. The guide works offline on Windows and Linux.

The project is split by platform:

## 🪟 [`WINDOWS/`](WINDOWS/README.md) — the main version

For the packaged app, open the [Build Windows EXE workflow](https://github.com/dragonballls/Fishing-Macro/actions/workflows/build-windows-exe.yml), choose the latest successful run, and download its `FishingMacro-Windows-x64` artifact. Extract it and run `FishingMacro.exe`. The artifact is temporary and may expire, so use the source steps below if it is unavailable.

Everything you need on Windows. Download this repository (green **Code** button →
**Download ZIP**), unzip it, then open the **`Windows`** folder and:

- double-click **`easy_run.py`**, or
- for the reliable path, open **PowerShell or Windows Terminal as
  administrator**, change to the `WINDOWS` folder, and run
  `python easy_run.py`. Why: if Roblox is elevated and the macro isn't, Windows
  drops its input and the bar drifts off and gives up.

Full setup, calibration, options, and troubleshooting are in
**[`WINDOWS/README.md`](WINDOWS/README.md)**.

**Want to fish without an NPC?** Select **Don't buy** in Setup. Fish-only mode
skips automatic buying/selling, NPC dialogue/movement, and Shift Lock checks.
Choose your fishing spot, aim, and Shift Lock state yourself before F2. Fishing
detectors and the safety watchdog remain active. This mode is shared by Windows
and Linux/Sober.

> **Do not assume an antivirus or download warning is a false positive.**
> Screen capture and automated input can attract heuristic warnings, but that
> does not establish the cause of a particular alert. Download from this
> repository and inspect the source and the warning before allowing anything.
> The source remains readable Python. Windows executables are built and smoke-tested
> by GitHub Actions; the downloadable artifact is temporary. Linux also includes
> readable setup shell/rules files. See `WINDOWS/README.md` for details.

## 🐧 [`LINUX/`](LINUX/README_LINUX.md) — experimental (Sober)

Runs the **same** macro on Linux against Roblox via
[Sober](https://sober.vinegarhq.org/) (X11 sessions), swapping only the
input/window layer for a `uinput` backend. It reuses the shared core in
`WINDOWS/` — the detection/control code is cross-platform; only `inputs.py` has a
Windows branch. Setup and the current limitations are in
**[`LINUX/README_LINUX.md`](LINUX/README_LINUX.md)**.

---

*Personal project shared as-is. Automating a game may be against its rules; use
at your own risk.*
