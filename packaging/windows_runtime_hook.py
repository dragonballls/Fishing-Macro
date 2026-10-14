"""Runtime settings for the packaged Windows GUI; source behavior is untouched.

The original Python launcher installs dependencies on first run. The packaged
executable already contains those dependencies, so the hook skips that install
and stores mutable user settings outside PyInstaller's temporary extraction
directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32" and getattr(sys, "frozen", False):
    app_data = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    runtime_root = app_data / "FishingMacro"
    runtime_root.mkdir(parents=True, exist_ok=True)

    # All required Python packages are bundled inside the executable.
    os.environ["BLOXFISH_NO_BOOT"] = "1"
    os.environ.setdefault("BLOXFISH_RUNTIME_ROOT", str(runtime_root))
    os.environ.setdefault(
        "BLOXFISH_GUI_ASSETS",
        str(Path(sys._MEIPASS) / "assets" / "gui"),
    )
