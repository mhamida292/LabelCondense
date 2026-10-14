"""OS-conditional code: opening PDFs for printing, revealing folders, and managing the Linux desktop menu."""
import os, pathlib, subprocess, sys

def _windows():
    """Whether we are on Windows, as an indirection tests can fake.

    Tests must patch this, never os.name: pathlib reads os.name when it
    constructs a Path, so a faked os.name makes Path() build the wrong
    concrete class and raise NotImplementedError on Python <= 3.12.
    """
    return os.name == "nt"

def _mac():
    """Whether we are on macOS; patched by tests like _windows()."""
    return sys.platform == "darwin"

def _data_home():
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
    return pathlib.Path(base)

def clean_env():
    """The environment for launching system programs. A frozen Linux build
    points LD_LIBRARY_PATH at its own bundled libraries; a desktop tool
    started with that can load the wrong ones and crash. PyInstaller keeps
    the user's original value in LD_LIBRARY_PATH_ORIG."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False) and "LD_LIBRARY_PATH" in env:
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            del env["LD_LIBRARY_PATH"]
    return env

def open_for_print(path):
    if _windows():
        os.startfile(str(path), "print")       # noqa: F821 - Windows only
    elif _mac():
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)], env=clean_env())

def reveal(path):
    d = path if path.is_dir() else path.parent
    if _windows():
        subprocess.Popen(["explorer", str(d)])
    elif _mac():
        subprocess.Popen(["open", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)], env=clean_env())

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
    if _windows() or _mac():
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

def icon_path():
    return _data_home() / "icons" / "hicolor" / "256x256" / "apps" / "label-condense.png"

def install_desktop_entry(exe, icon=None):
    """`icon`: the app's PNG, copied where the menu looks for icons. Without
    one the entry falls back to a stock printer icon."""
    p = desktop_entry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    icon_name = "document-print"
    if icon is not None and pathlib.Path(icon).is_file():
        import shutil
        icon_path().parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon, icon_path())
        icon_name = "label-condense"
    quoted_exe = _quote_exec_path(exe)
    p.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Label Condense\n"
        "Comment=Rebuild a Whatnot export into print-ready packing slips\n"
        f"Icon={icon_name}\n"
        f"Exec={quoted_exe} %f\n"
        "Terminal=false\n"
        "MimeType=application/pdf;\n"
        "Categories=Utility;\n",
        encoding="utf-8")
    p.chmod(0o755)
    _legacy_desktop_entry_path().unlink(missing_ok=True)
    return p

def _quiet(argv):
    """A short probe's stdout, or '' if the tool is missing, fails or hangs."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=2,
                              env=clean_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

def prefers_dark():
    """Whether the desktop is set to dark mode. Read once at startup; any
    doubt means light."""
    if _windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False
    if _mac():
        return _quiet(["defaults", "read", "-g", "AppleInterfaceStyle"]).strip() == "Dark"
    # The freedesktop portal answers for KDE and GNOME alike: 1 means dark.
    portal = _quiet(["gdbus", "call", "--session",
                     "--dest", "org.freedesktop.portal.Desktop",
                     "--object-path", "/org/freedesktop/portal/desktop",
                     "--method", "org.freedesktop.portal.Settings.Read",
                     "org.freedesktop.appearance", "color-scheme"])
    if "uint32" in portal:
        return "uint32 1" in portal
    return "dark" in _quiet(["gsettings", "get", "org.gnome.desktop.interface",
                             "color-scheme"])
