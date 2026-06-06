def pre_find_module_path(hook_api):
    # Allow tkinter to be analyzed even when PyInstaller's automatic Tcl/Tk
    # probe fails on this machine. We bundle Tcl/Tk manually in the spec.
    return
