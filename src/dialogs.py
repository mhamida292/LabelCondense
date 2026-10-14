"""File pickers. Tk's own dialog is the system one on Windows and macOS but a
bare-bones Tk window on Linux, so there we ask the desktop's picker (kdialog
on KDE, zenity on GNOME) and fall back to Tk only if neither is installed or
it fails to start. `filters` is a list of (label, "*.a *.b")."""
import os, pathlib, shutil, subprocess, sys, threading, time
from tkinter import filedialog, TclError

import platform_bits

_busy = False

def _native_tool():
    if not sys.platform.startswith("linux"):
        return None
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    order = ("kdialog", "zenity") if kde else ("zenity", "kdialog")
    return next((t for t in order if shutil.which(t)), None)

def _argv(tool, save, title, start, filters):
    if tool == "kdialog":
        flt = "\n".join(f"{label} ({pats})" for label, pats in filters)
        return ["kdialog", "--title", title,
                "--getsavefilename" if save else "--getopenfilename", str(start), flt]
    argv = ["zenity", "--file-selection", f"--title={title}", f"--filename={start}"]
    if save:
        argv.append("--save")
    return argv + [f"--file-filter={label} | {pats}" for label, pats in filters]

def _run(root, argv):
    """Run the picker off the Tk thread and keep the window painting, so the
    desktop doesn't mark it "not responding" while the user browses.
    Returns the CompletedProcess, or None if the tool could not run."""
    box = {}
    def work():
        try:
            box["r"] = subprocess.run(argv, capture_output=True, text=True,
                                      env=platform_bits.clean_env())
        except OSError:
            pass
    t = threading.Thread(target=work, daemon=True); t.start()
    while t.is_alive():
        try:
            root.update()
        except TclError:           # the window was closed meanwhile
            t.join(); return None
        time.sleep(0.03)
    return box.get("r")

def _native(root, save, title, start, filters):
    """The chosen path, '' if cancelled, or None to fall back to Tk."""
    tool = _native_tool()
    if tool is None:
        return None
    r = _run(root, _argv(tool, save, title, start, filters))
    if r is None or r.returncode not in (0, 1):
        return None
    return r.stdout.strip() if r.returncode == 0 else ""

def ask_open(root, title, initialdir, filters):
    global _busy
    if _busy:
        return ""
    _busy = True
    try:
        got = _native(root, False, title, pathlib.Path(initialdir), filters)
        if got is None:
            got = filedialog.askopenfilename(parent=root, title=title,
                                             initialdir=str(initialdir), filetypes=filters)
        return got or ""
    finally:
        _busy = False

def ask_save(root, title, initialdir, initialfile, filters, ext):
    """`ext` (".pdf") is added when the user leaves it off."""
    global _busy
    if _busy:
        return ""
    _busy = True
    try:
        got = _native(root, True, title, pathlib.Path(initialdir) / initialfile, filters)
        if got is None:
            got = filedialog.asksaveasfilename(parent=root, title=title,
                                               initialdir=str(initialdir), initialfile=initialfile,
                                               defaultextension=ext, filetypes=filters)
        elif got and not pathlib.Path(got).suffix:
            got += ext
        return got or ""
    finally:
        _busy = False
