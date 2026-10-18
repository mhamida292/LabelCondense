"""Where exports come from: the folder last used, and the newest Whatnot
export waiting in it, so a normal print day is one click instead of a browse."""
import datetime as dt, json, os, pathlib, re

import branding

# Whatnot names its downloads Whatnot-Combined-Labels-Packing-Slips-<id>-1.pdf;
# a browser may add " (1)". Nothing else counts: offering some other PDF would
# just fail its audit.
RE_EXPORT = re.compile(r'whatnot.*(label|slip).*\.pdf$', re.I)
MAX_AGE = dt.timedelta(days=7)

def _prefs_path():
    return branding.settings_dir() / "prefs.json"

def _prefs():
    try:
        d = json.loads(_prefs_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def get_pref(key, default):
    """A saved preference, or `default` when absent or of the wrong type."""
    v = _prefs().get(key, default)
    return v if isinstance(v, type(default)) else default

def set_pref(key, value):
    """Save one preference. Never raises: forgetting one costs a click, not a run."""
    d = _prefs(); d[key] = value
    tmp = _prefs_path().with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, _prefs_path())
    except (OSError, TypeError, ValueError):
        pass

def remember_folder(path):
    """Record the folder an export came from."""
    set_pref("export_dir", str(pathlib.Path(path).parent))

def downloads():
    return pathlib.Path.home() / "Downloads"

def export_dir():
    """Where the file picker opens: the last folder used, else Downloads."""
    for d in (_prefs().get("export_dir"), downloads(), pathlib.Path.home()):
        if d and pathlib.Path(d).is_dir():
            return pathlib.Path(d)
    return pathlib.Path.home()

def newest_export(now=None):
    """The most recent Whatnot export (path, modified) in Downloads or the
    last-used folder, if one arrived in the past week; else None."""
    now = now or dt.datetime.now()
    best = None
    for d in {downloads(), export_dir()}:
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if not RE_EXPORT.search(e.name):
                continue
            try:
                if not e.is_file():
                    continue
                when = dt.datetime.fromtimestamp(e.stat().st_mtime)
            except OSError:
                continue
            if now - when <= MAX_AGE and (best is None or when > best[1]):
                best = (pathlib.Path(e.path), when)
    return best

def age(when, now=None):
    s = int(((now or dt.datetime.now()) - when).total_seconds())
    if s < 60:       return "just now"
    if s < 3600:     return f"{s // 60} min ago"
    if s < 86400:    return f"{s // 3600} h ago"
    if s < 172800:   return "yesterday"
    return f"{s // 86400} days ago"

def short(name, n=44):
    return name if len(name) <= n else name[:n - 16] + "…" + name[-15:]
