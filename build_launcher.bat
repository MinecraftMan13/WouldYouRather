@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment Python not found at .venv\Scripts\python.exe
    exit /b 1
)

set "PYTHON_HOME=%LocalAppData%\Programs\Python\Python311"
set "TCL_LIBRARY=%PYTHON_HOME%\tcl\tcl8.6"
set "TK_LIBRARY=%PYTHON_HOME%\tcl\tk8.6"

if not exist "%TCL_LIBRARY%\init.tcl" (
    echo Tcl library not found at %TCL_LIBRARY%
    exit /b 1
)

if not exist "%TK_LIBRARY%\tk.tcl" (
    echo Tk library not found at %TK_LIBRARY%
    exit /b 1
)

.\.venv\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --clean ^
    WouldYouRatherLauncher.spec
