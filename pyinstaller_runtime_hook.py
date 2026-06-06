from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    base_path = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    tcl_library = base_path / "_tcl_data"
    tk_library = base_path / "_tk_data"

    if tcl_library.exists():
        os.environ["TCL_LIBRARY"] = str(tcl_library)

    if tk_library.exists():
        os.environ["TK_LIBRARY"] = str(tk_library)
