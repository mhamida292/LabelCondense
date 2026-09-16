"""OS-conditional code: opening PDFs for printing, revealing folders, and managing the Linux desktop menu."""
import os, pathlib, subprocess, sys

def _windows():
    """Whether we are on Windows, as an indirection tests can fake.

    Tests must patch this, never os.name: pathlib reads os.name when it
    constructs a Path, so a faked os.name makes Path() build the wrong
    concrete class and raise NotImplementedError on Python <= 3.12.
    """
    return os.name == "nt"

def _data_home():
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
    return pathlib.Path(base)

def open_for_print(path):
    if _windows():
        os.startfile(str(path), "print")       # noqa: F821 - Windows only
    else:
        subprocess.Popen(["xdg-open", str(path)])

def reveal(path):
    d = path if path.is_dir() else path.parent
    if _windows():
        subprocess.Popen(["explorer", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])

def desktop_entry_path():
    return _data_home() / "applications" / "label-condense.desktop"

def _legacy_desktop_entry_path():
    """Left behind by builds from when the app was called Packing Slips."""
    return _data_home() / "applications" / "packing-slips.desktop"

def _choice_file():
    return _data_home() / "label-condense" / "desktop-entry-declined"

def _legacy_choice_file():
    return _data_home() / "packing-slips" / "desktop-entry-declined"

def should_offer_desktop_entry():
    if _windows():
        return False
    if not getattr(sys, "frozen", False):
        return False
    return not (_choice_file().exists() or _legacy_choice_file().exists()
                or desktop_entry_path().exists())

def remember_desktop_choice(yes):
    if yes:
        return
    f = _choice_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("declined\n")

def _quote_exec_path(exe):
    """Quote a path for the Exec= line per freedesktop desktop-entry spec.

    Escapes backslashes first, then ", `, and $ with backslashes,
    then wraps the result in double quotes. The %f argument stays outside.
    """
    # Escape backslashes first, then the other reserved characters
    escaped = exe.replace("\\", "\\\\")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("`", "\\`")
    escaped = escaped.replace("$", "\\$")
    return f'"{escaped}"'

def install_desktop_entry(exe):
    p = desktop_entry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    quoted_exe = _quote_exec_path(exe)
    p.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Label Condense\n"
        "Comment=Rebuild a Whatnot export into print-ready packing slips\n"
        "Icon=document-print\n"
        f"Exec={quoted_exe} %f\n"
        "Terminal=false\n"
        "MimeType=application/pdf;\n"
        "Categories=Utility;\n",
        encoding="utf-8")
    p.chmod(0o755)
    _legacy_desktop_entry_path().unlink(missing_ok=True)
    return p
