# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


project_dir = Path.cwd()
python_home = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311"

datas = collect_data_files("customtkinter")
datas += [
    (str(python_home / "tcl" / "tcl8.6"), "_tcl_data"),
    (str(python_home / "tcl" / "tk8.6"), "_tk_data"),
]

binaries = [
    (str(python_home / "DLLs" / "_tkinter.pyd"), "."),
    (str(python_home / "DLLs" / "tcl86t.dll"), "."),
    (str(python_home / "DLLs" / "tk86t.dll"), "."),
]

hiddenimports = [
    "tkinter",
    "tkinter.constants",
    "tkinter.filedialog",
    "tkinter.font",
    "tkinter.ttk",
    "customtkinter",
]

a = Analysis(
    ["launcher_gui.py"],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_dir / "hooks")],
    hooksconfig={},
    runtime_hooks=["pyinstaller_runtime_hook.py"],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WouldYouRatherLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\serverstack.ico"],
)
