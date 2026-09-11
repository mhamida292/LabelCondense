"""The four places this program has to care which OS it is on."""
import os, pathlib, subprocess, sys

def _data_home():
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
    return pathlib.Path(base)

def open_for_print(path):
    if os.name == "nt":
        os.startfile(str(path), "print")       # noqa: F821 - Windows only
    else:
        subprocess.Popen(["xdg-open", str(path)])

def reveal(path):
    d = path if path.is_dir() else path.parent
    if os.name == "nt":
        subprocess.Popen(["explorer", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])

def desktop_entry_path():
    return _data_home() / "applications" / "packing-slips.desktop"

def _choice_file():
    return _data_home() / "packing-slips" / "desktop-entry-declined"

def should_offer_desktop_entry():
    if os.name == "nt":
        return False
    if not getattr(sys, "frozen", False):
        return False
    return not (_choice_file().exists() or desktop_entry_path().exists())

def remember_desktop_choice(yes):
    if yes:
        return
    f = _choice_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("declined\n")

def install_desktop_entry(exe):
    p = desktop_entry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Packing Slips\n"
        "Comment=Rebuild a Whatnot export into print-ready packing slips\n"
        "Icon=document-print\n"
        f"Exec={exe} %f\n"
        "Terminal=false\n"
        "MimeType=application/pdf;\n"
        "Categories=Utility;\n",
        encoding="utf-8")
    p.chmod(0o755)
    return p
