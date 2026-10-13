"""Where run reports are kept. Reports contain buyer usernames on failure
lines, so they live in the user's own data directory — never in the bundle,
which is a temp dir that vanishes, and never anywhere shared."""
import datetime as dt, json, os, pathlib
from dataclasses import dataclass

APP = "LabelCondense"

@dataclass
class Report:
    path: pathlib.Path
    when: dt.datetime
    source: str
    ok: bool

def _adopt_legacy(base, old, new):
    """The app was called Packing Slips; carry its data directory (reports,
    the declined-menu-entry marker) over to the new name on first use."""
    if (base / old).is_dir() and not (base / new).exists():
        (base / old).rename(base / new)
    return base / new

def data_dir():
    """The app's own per-user folder. Logs and branding settings live in it."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData/Local")
        return _adopt_legacy(pathlib.Path(base), "PackingSlips", APP)
    base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
    return _adopt_legacy(pathlib.Path(base), "packing-slips", "label-condense")

def log_dir():
    override = os.environ.get("PACKING_LOG_DIR")
    d = pathlib.Path(override) if override else data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_report(text, source_name, ok, when=None):
    when = when or dt.datetime.now()
    stamp = when.strftime("%Y%m%d-%H%M%S")
    path = log_dir() / f"{stamp}-{'ok' if ok else 'FAIL'}.log"
    n = 1
    while path.exists():
        n += 1
        path = log_dir() / f"{stamp}-{n}-{'ok' if ok else 'FAIL'}.log"
    meta = json.dumps({"source": source_name, "ok": ok, "when": when.isoformat()})
    path.write_text(f"#meta {meta}\n{text}\n", encoding="utf-8")
    return path

def _read_meta(path):
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        if not first.startswith("#meta "):
            return None
        m = json.loads(first[6:])
        return Report(path, dt.datetime.fromisoformat(m["when"]), m["source"], bool(m["ok"]))
    except (ValueError, KeyError, OSError):
        return None

def list_reports():
    out = [r for r in (_read_meta(p) for p in log_dir().glob("*.log")) if r]
    out.sort(key=lambda r: r.when, reverse=True)
    return out

def label(r):
    return (f"{r.when.strftime('%-d %b %H:%M') if os.name != 'nt' else r.when.strftime('%#d %b %H:%M')}"
            f" — {r.source} · {'passed' if r.ok else 'FAILED'}")

def prune(days=30):
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    n = 0
    for r in list_reports():
        if r.when < cutoff:
            r.path.unlink(missing_ok=True)
            n += 1
    return n
