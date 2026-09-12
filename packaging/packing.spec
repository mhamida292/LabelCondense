# -*- mode: python ; coding: utf-8 -*-
import pathlib, sys
root = pathlib.Path(SPECPATH).parent
binaries = [(str(p), "bin") for p in (root / "packaging" / "bin").glob("*")]

# libxcb.so.1 is a transitive dependency of gs/poppler (via libX11) that
# collect_binaries.py already stages into packaging/bin/. PyInstaller's own
# Tk/X11 auto-collection deliberately refuses to bundle libxcb (its ABI
# drifts too much across distros — see PyInstaller's dylib exclude list), so
# it expects the target system to provide it. To keep the promise that the
# bundle needs nothing preinstalled, also place our already-harvested copy
# at the top level, alongside the auto-bundled libX11.so.6 that needs it.
_xcb = root / "packaging" / "bin" / "libxcb.so.1"
if _xcb.exists():
    binaries.append((str(_xcb), "."))

# Ghostscript's own Resource/Init/lib tree (gs_init.ps and friends), staged
# by collect_binaries.py, has no home directory on a clean-room machine.
_gs_resources = root / "packaging" / "gs-resources"
datas = [(str(_gs_resources), "gs-resources")] if _gs_resources.exists() else []

a = Analysis(
    [str(root / "src" / "packing_gui.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["pytest", "numpy", "matplotlib"],
    runtime_hooks=[str(root / "packaging" / "rthook_gs_env.py")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="packing-slips",
    console=False,
    upx=False,
)
