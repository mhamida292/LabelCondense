"""The window's look: the Sun Valley ttk theme, vendored in assets/sv with its
accent recoloured teal (packaging/make_theme.py), light or dark to match the
system. Widgets that ttk doesn't theme -- tk.Text, hand-coloured labels -- take
their colours from palette()."""
import pathlib, sys, tkinter as tk
from tkinter import ttk

import platform_bits

PALETTE = {
    "light": dict(fg="#1c1c1c", muted="#6a6d73", field="#ffffff",
                  border="#d0d0d0", ok="#1f7a3f", bad="#b3261e"),
    "dark":  dict(fg="#fafafa", muted="#9a9da3", field="#2b2b2b",
                  border="#3a3a3a", ok="#6fd08c", bad="#ff8a80"),
}

def asset(name):
    base = getattr(sys, "_MEIPASS", None)
    return (pathlib.Path(base) if base else pathlib.Path(__file__).parent) / "assets" / name

def mode(root):
    return "dark" if ttk.Style(root).theme_use() == "sun-valley-dark" else "light"

def palette(root):
    return PALETTE[mode(root)]

def apply(root, dark=None):
    """Load the theme and the window icon. A missing or broken theme leaves
    Tk's default look; the app works the same either way."""
    if dark is None:
        dark = platform_bits.prefers_dark()
    style = ttk.Style(root)
    try:
        if "sun-valley-light" not in style.theme_names():
            root.tk.call("source", str(asset("sv/sv.tcl")))
        style.theme_use("sun-valley-dark" if dark else "sun-valley-light")
    except tk.TclError:
        pass
    try:
        root._icon = tk.PhotoImage(file=str(asset("icon-256.png")))
        root.iconphoto(True, root._icon)
    except tk.TclError:
        pass
