"""PyInstaller runtime hook: point Ghostscript at its bundled Resource/lib
tree before any application code runs. Without this, a frozen gs fails at
the very last step of a run with "Can't find initialization file gs_init.ps"
because it looks for /usr/share/ghostscript/<version> by default, which
does not exist on a clean-room machine."""
import os, sys

_base = getattr(sys, "_MEIPASS", None)
if _base:
    _resources = os.path.join(_base, "gs-resources")
    if os.path.isdir(_resources):
        os.environ["GS_LIB"] = os.pathsep.join([
            os.path.join(_resources, "Resource", "Init"),
            os.path.join(_resources, "lib"),
            os.path.join(_resources, "iccprofiles"),
        ])
