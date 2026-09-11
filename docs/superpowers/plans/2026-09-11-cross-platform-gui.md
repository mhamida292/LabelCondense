# Cross-Platform GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one downloadable, double-clickable file per OS (Windows and Linux) that turns a Whatnot export into a print-ready PDF, with no installation of anything.

**Architecture:** A tkinter window (`packing_gui.py`) imports the existing `whatnot_slips` module and calls `build()`/`verify()` on a worker thread, reporting progress through a queue drained by the Tk main loop. PyInstaller freezes Python, Ghostscript and Poppler into a single executable per OS; a binary resolver makes the existing code find those bundled binaries instead of relying on PATH. GitHub Actions builds both on a version tag and attaches them to a Release.

**Tech Stack:** Python 3, tkinter (stdlib), Pillow, Ghostscript, Poppler (pdftotext/pdfimages), PyInstaller, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-11-cross-platform-gui-design.md`

## Global Constraints

- **The audit is the safety net.** Every task that touches `whatnot_slips.py` must end with the parity test from Task 1 passing. Rendering and audit logic do not change.
- **CLI behaviour must not change.** `python3 whatnot_slips.py build IN.pdf -o OUT.pdf --deep` and `verify` keep identical arguments, stdout format, and exit codes.
- **`_run` is taken.** `whatnot_slips.py:493` already defines `_run(args)` as the CLI dispatcher. The subprocess wrapper introduced in Task 2 is named `_spawn`.
- **Ghostscript on Windows is `gswin64c.exe`.** There is no `gs` on Windows.
- **Linux CI runner is pinned to `ubuntu-22.04`** to keep the glibc floor low.
- **Log directories:** `%LOCALAPPDATA%\PackingSlips\logs` (Windows), `~/.local/share/packing-slips/logs` (Linux). Retention 30 days.
- **Real exports contain customer data.** No PDF fixture is ever committed. Tests that need one read `PACKING_TEST_PDF` from the environment and skip with a clear message when it is unset.
- **No raw traceback ever reaches the main window.** Tracebacks go to the log.
- **Copy is fixed by the spec:** the failure screen says `DO NOT PRINT` and "This export failed its checks. Nothing was saved."

## Prerequisites (do these first, they need sudo)

```bash
sudo apt install -y python3-tk
cd "/home/mhamida/Desktop/Projects/Packing Logistics"
python3 -m venv .venv
.venv/bin/pip install pytest pyinstaller pillow
```

Verify: `.venv/bin/python -c "import tkinter, PIL, pytest; print('ok')"`

---

### Task 1: Test harness, parity baseline, and source move

Establishes the safety net before anything is refactored, then moves the module
out of the hidden `.packing/` directory so it can be imported by tests and
frozen by PyInstaller. `.packing/` stays as the runtime data directory.

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_parity.py`
- Create: `pytest.ini`
- Move: `.packing/whatnot_slips.py` → `src/whatnot_slips.py`
- Modify: `run.sh:8` (the `TOOL=.packing` line)
- Modify: `.gitignore` (add `.venv/`, `__pycache__/`, `.pytest_cache/`)

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/conftest.py::sample_pdf` fixture (a `pathlib.Path` to a real export, or skip); `tests/test_parity.py::semantic_fingerprint(pdf) -> dict` used by every later task to prove nothing changed.

- [ ] **Step 1: Write the parity fingerprint and its test**

Ghostscript stamps `/CreationDate` into every PDF it writes, so two correct runs
are never byte-identical. Parity is therefore semantic: same page count, same
text on every page, same audit totals.

`tests/conftest.py`:

```python
import os, pathlib, pytest

@pytest.fixture(scope="session")
def sample_pdf():
    p = os.environ.get("PACKING_TEST_PDF")
    if not p:
        pytest.skip("set PACKING_TEST_PDF to a real Whatnot export to run parity tests")
    path = pathlib.Path(p)
    if not path.is_file():
        pytest.skip(f"PACKING_TEST_PDF does not exist: {path}")
    return path
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = src
```

`tests/test_parity.py`:

```python
import hashlib, json, pathlib, subprocess, tempfile
import pytest
import whatnot_slips as ws

BASELINE = pathlib.Path(__file__).parent / "baseline.json"

def semantic_fingerprint(pdf):
    """Timestamp-immune description of a built PDF."""
    pages = ws.pdf_pages(str(pdf))
    return {
        "pages": len(pages),
        "text_sha": hashlib.sha256("\f".join(pages).encode()).hexdigest(),
    }

def build_and_fingerprint(src, tmpdir):
    out = pathlib.Path(tmpdir) / "out.pdf"
    n, nsl, nlb = ws.build(str(src), str(out), quiet=True)
    audit = ws.verify(str(src), str(out), deep=False)
    fp = semantic_fingerprint(out)
    fp.update(shipments=n, slip_pages=nsl, labels=nlb,
              checks=audit.checks, failures=len(audit.fail))
    return fp

def test_build_matches_baseline(sample_pdf):
    if not BASELINE.exists():
        pytest.skip("no baseline recorded yet; run tests/record_baseline.py")
    with tempfile.TemporaryDirectory() as td:
        got = build_and_fingerprint(sample_pdf, td)
    assert got == json.loads(BASELINE.read_text())

def test_audit_passes_clean(sample_pdf):
    with tempfile.TemporaryDirectory() as td:
        fp = build_and_fingerprint(sample_pdf, td)
    assert fp["failures"] == 0
```

- [ ] **Step 2: Write the baseline recorder**

`tests/record_baseline.py`:

```python
"""Record the current build's fingerprint, BEFORE any refactor.
Usage: PACKING_TEST_PDF=/path/to/export.pdf .venv/bin/python tests/record_baseline.py
"""
import json, os, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from test_parity import build_and_fingerprint

src = pathlib.Path(os.environ["PACKING_TEST_PDF"])
with tempfile.TemporaryDirectory() as td:
    fp = build_and_fingerprint(src, td)
out = pathlib.Path(__file__).parent / "baseline.json"
out.write_text(json.dumps(fp, indent=2, sort_keys=True) + "\n")
print("recorded", fp)
```

- [ ] **Step 3: Move the module and fix run.sh**

```bash
cd "/home/mhamida/Desktop/Projects/Packing Logistics"
mkdir -p src
git mv .packing/whatnot_slips.py src/whatnot_slips.py
sed -i 's|^TOOL=\.packing$|TOOL=src|' run.sh
```

`run.sh` keeps `ARCH=$TOOL/archive`-style paths pointing at runtime data, so
also change those two lines back to `.packing`:

```bash
sed -i 's|^IN=inbox; OUTBOX=outbox; ARCH=\$TOOL/archive; LOGS=\$TOOL/logs$|IN=inbox; OUTBOX=outbox; ARCH=.packing/archive; LOGS=.packing/logs|' run.sh
```

Verify by eye that `run.sh` now has `TOOL=src` and `.packing/archive`,
`.packing/logs`.

- [ ] **Step 4: Record the baseline against a real export**

```bash
cd "/home/mhamida/Desktop/Projects/Packing Logistics"
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/python tests/record_baseline.py
```

Expected: prints a dict with `failures: 0` and writes `tests/baseline.json`.

- [ ] **Step 5: Run the parity tests and the CLI**

```bash
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/pytest -v
./run.sh --fast   # proves the moved module still works end to end
```

Expected: both parity tests PASS; `run.sh` reports OK (or "inbox/ is empty",
which is also fine — the point is no import error).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: parity harness and baseline; move module to src/

Ghostscript stamps a creation date into every PDF, so parity is semantic —
page count, per-page text, and audit totals — not a byte hash.
baseline.json is recorded from a real export that is never committed."
```

`tests/baseline.json` holds only counts and a hash of text, no customer data, so
it is safe to commit. Confirm with `cat tests/baseline.json` before committing.

---

### Task 2: Binary resolution and windowed subprocess

The only change to audited code that affects how external tools are invoked.

**Files:**
- Modify: `src/whatnot_slips.py` (add `_bin`/`_spawn`; change 3 call sites at `:93`, `:274`, `:314` — line numbers shift after the additions, find them by name)
- Test: `tests/test_bin.py`

**Interfaces:**
- Consumes: Task 1's parity test.
- Produces: `whatnot_slips._bin(name: str) -> str`, `whatnot_slips._spawn(argv: list[str], **kw) -> subprocess.CompletedProcess`.

- [ ] **Step 1: Write the failing test**

`tests/test_bin.py`:

```python
import os, subprocess, sys
import whatnot_slips as ws

def test_unfrozen_returns_bare_name(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert ws._bin("gs") == "gs"
    assert ws._bin("pdftotext") == "pdftotext"

def test_frozen_posix_uses_bundle_bin(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)
    monkeypatch.setattr(os, "name", "posix")
    assert ws._bin("gs") == os.path.join("/bundle", "bin", "gs")

def test_frozen_windows_maps_ghostscript_name(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\bundle", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    assert ws._bin("gs").endswith("gswin64c.exe")
    assert ws._bin("pdftotext").endswith("pdftotext.exe")

def test_spawn_passes_through_and_checks(tmp_path):
    r = ws._spawn([sys.executable, "-c", "print('hi')"], capture_output=True, text=True)
    assert r.stdout.strip() == "hi"

def test_spawn_raises_on_failure():
    import pytest
    with pytest.raises(subprocess.CalledProcessError):
        ws._spawn([sys.executable, "-c", "raise SystemExit(3)"])
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_bin.py -v
```

Expected: FAIL — `AttributeError: module 'whatnot_slips' has no attribute '_bin'`.

- [ ] **Step 3: Implement**

Add near the top of `src/whatnot_slips.py`, after the imports:

```python
# ------------------------------------------------------- external binaries
# Frozen bundles carry gs and poppler under bin/; unfrozen we use PATH as before.
_WIN_NAMES = {'gs': 'gswin64c.exe'}

def _bin(name):
    base = getattr(sys, '_MEIPASS', None)
    if not base:
        return name
    exe = _WIN_NAMES.get(name, name + '.exe') if os.name == 'nt' else name
    return os.path.join(base, 'bin', exe)

def _spawn(argv, **kw):
    """subprocess.run with check=True, and no console flash on Windows.
    A windowed .exe pops a console for every child process without this."""
    kw.setdefault('check', True)
    if os.name == 'nt':
        kw.setdefault('creationflags', 0x08000000)   # CREATE_NO_WINDOW
    return subprocess.run(argv, **kw)
```

Then change the three call sites (search for them; do not trust line numbers):

```python
# in pdf_pages()
_spawn([_bin('pdftotext'), '-layout', '-enc', 'UTF-8', pdf, tmp])

# in label_bitmap()
_spawn([_bin('pdfimages'), '-p', '-f', str(pageno), '-l', str(pageno),
        pdf, os.path.join(tmpdir, 'L')])

# in build()
_spawn([_bin('gs'),'-q','-dBATCH','-dNOPAUSE','-sDEVICE=pdfwrite',
    '-dCompatibilityLevel=1.4','-dEmbedAllFonts=true','-dSubsetFonts=true',
    '-dAutoFilterMonoImages=false','-dMonoImageFilter=/FlateEncode',
    '-dDownsampleMonoImages=false','-dFIXEDMEDIA',
    f'-dDEVICEWIDTHPOINTS={W}', f'-dDEVICEHEIGHTPOINTS={H}',
    f'-sOutputFile={out}', psfile])
```

Each replaces a `subprocess.run(..., check=True)` call; drop the now-redundant
`check=True`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_bin.py -v
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/pytest -v
```

Expected: all PASS, including both parity tests. Parity passing here is the
proof that swapping the invocation changed nothing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: resolve bundled binaries and suppress Windows console flash"
```

---

### Task 3: Progress callback and capturable audit text

Makes a 90-second run observable from a GUI without changing what the CLI prints.

**Files:**
- Modify: `src/whatnot_slips.py` (`build`, `verify`, `Audit`)
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `build(src, out, quiet=False, progress=None) -> tuple[int,int,int]` where `progress(done: int, total: int, stage: str)`.
  - `verify(src, out, deep=False, progress=None) -> Audit` with the same callback shape.
  - `Audit.text(title: str) -> str` — the report as a string. `Audit.report(title)` prints `text()` and returns `not self.fail`, exactly as before.
  - Stage strings are exactly `"building slips"` and `"checking labels"`.

- [ ] **Step 1: Write the failing test**

`tests/test_progress.py`:

```python
import whatnot_slips as ws

def test_audit_text_matches_report(capsys):
    a = ws.Audit()
    a.ok(True, "fine")
    a.ok(False, "broken", "detail here")
    text = a.text("AUDIT")
    ok = a.report("AUDIT")
    printed = capsys.readouterr().out
    assert ok is False
    assert text.strip() == printed.strip()
    assert "assertions run : 2" in text
    assert "failures       : 1" in text
    assert "FAIL broken: detail here" in text

def test_audit_text_clean_run():
    a = ws.Audit()
    a.ok(True, "fine")
    assert "failures       : 0" in a.text("AUDIT")

def test_build_reports_progress(sample_pdf, tmp_path):
    seen = []
    out = tmp_path / "o.pdf"
    ws.build(str(sample_pdf), str(out), quiet=True,
             progress=lambda d, t, s: seen.append((d, t, s)))
    assert seen, "progress callback was never called"
    assert all(s == "building slips" for _, _, s in seen)
    assert [d for d, _, _ in seen] == sorted(d for d, _, _ in seen)
    assert seen[-1][0] == seen[-1][1]          # reaches the total
    assert seen[-1][1] > 0

def test_verify_reports_progress(sample_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    ws.build(str(sample_pdf), str(out), quiet=True)
    seen = []
    ws.verify(str(sample_pdf), str(out), deep=True,
              progress=lambda d, t, s: seen.append((d, t, s)))
    assert seen
    assert all(s == "checking labels" for _, _, s in seen)
    assert seen[-1][0] == seen[-1][1]
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/pytest tests/test_progress.py -v
```

Expected: FAIL — `Audit` has no attribute `text`; `build() got an unexpected keyword argument 'progress'`.

- [ ] **Step 3: Implement**

In `class Audit`, replace `report` with:

```python
    def text(self, title):
        lines = [f"\n{title}",
                 f"  assertions run : {self.checks}",
                 f"  failures       : {len(self.fail)}"]
        for l, d in self.fail[:40]:
            lines.append(f"    FAIL {l}: {d}")
        if len(self.fail) > 40:
            lines.append(f"    ... and {len(self.fail)-40} more")
        return "\n".join(lines)

    def report(self, title):
        print(self.text(title))
        return not self.fail
```

In `build`, change the signature and the progress line:

```python
def build(src, out, quiet=False, progress=None):
```

and replace the tty print block inside the loop with:

```python
            if progress:
                progress(i + 1, len(data), "building slips")
            elif not quiet and sys.stderr.isatty():
                print(f"\r  rendering {i+1}/{len(data)}", end='', file=sys.stderr, flush=True)
    if not progress and not quiet and sys.stderr.isatty():
        print(file=sys.stderr)
```

In `verify`, change the signature to `def verify(src, out, deep=False, progress=None):`
and replace its label-checking tty print (near the end of the function, the
`checking label {k+1}` block) with:

```python
                if progress:
                    progress(k + 1, len(src_ships), "checking labels")
                elif sys.stderr.isatty():
                    print(f"\r  checking label {k+1}/{len(src_ships)}", end='',
                          file=sys.stderr, flush=True)
            if not progress and sys.stderr.isatty(): print(file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/pytest -v
./run.sh --fast
```

Expected: all PASS. `run.sh` output unchanged — the tty path is untouched when
no callback is passed.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: progress callbacks and capturable audit text"
```

---

### Task 4: Log store

Where reports live, how they are named, how they are pruned, how they are listed.

**Files:**
- Create: `src/logstore.py`
- Test: `tests/test_logstore.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `log_dir() -> pathlib.Path` — creates and returns the per-user log directory.
  - `write_report(text: str, source_name: str, ok: bool, when: datetime | None = None) -> pathlib.Path`
  - `list_reports() -> list[Report]` newest first, where `Report` is a `dataclass` with fields `path: pathlib.Path`, `when: datetime`, `source: str`, `ok: bool`.
  - `label(r: Report) -> str` — dropdown text, e.g. `"11 Sep 09:01 — test.pdf · passed"` / `"· FAILED"`.
  - `prune(days: int = 30) -> int` — deletes older reports, returns how many.

- [ ] **Step 1: Write the failing test**

`tests/test_logstore.py`:

```python
import datetime as dt
import logstore

def test_log_dir_is_per_user_and_created(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    d = logstore.log_dir()
    assert d.is_dir()
    assert d == tmp_path / "logs"

def test_write_and_list_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    when = dt.datetime(2026, 9, 11, 9, 1, 41)
    p = logstore.write_report("AUDIT\n  failures       : 0", "test.pdf", True, when)
    assert p.exists()
    reports = logstore.list_reports()
    assert len(reports) == 1
    r = reports[0]
    assert r.source == "test.pdf" and r.ok is True and r.when == when
    assert "failures       : 0" in r.path.read_text()

def test_failed_reports_are_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    logstore.write_report("boom", "bad.pdf", False, dt.datetime(2026, 9, 10, 18, 44))
    r = logstore.list_reports()[0]
    assert r.ok is False
    assert logstore.label(r) == "10 Sep 18:44 — bad.pdf · FAILED"

def test_listing_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    logstore.write_report("a", "old.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    logstore.write_report("b", "new.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    assert [r.source for r in logstore.list_reports()] == ["new.pdf", "old.pdf"]

def test_prune_removes_only_old(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    now = dt.datetime.now()
    logstore.write_report("old", "old.pdf", True, now - dt.timedelta(days=40))
    logstore.write_report("new", "new.pdf", True, now)
    assert logstore.prune(30) == 1
    assert [r.source for r in logstore.list_reports()] == ["new.pdf"]

def test_source_name_with_spaces_and_unicode(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    logstore.write_report("x", "my export (2).pdf", True, dt.datetime(2026, 9, 11, 10, 0))
    assert logstore.list_reports()[0].source == "my export (2).pdf"
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_logstore.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'logstore'`.

- [ ] **Step 3: Implement**

`src/logstore.py`:

```python
"""Where run reports are kept. Reports contain buyer usernames on failure
lines, so they live in the user's own data directory — never in the bundle,
which is a temp dir that vanishes, and never anywhere shared."""
import datetime as dt, json, os, pathlib, re
from dataclasses import dataclass

APP = "PackingSlips"

@dataclass
class Report:
    path: pathlib.Path
    when: dt.datetime
    source: str
    ok: bool

def log_dir():
    override = os.environ.get("PACKING_LOG_DIR")
    if override:
        d = pathlib.Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData/Local")
        d = pathlib.Path(base) / APP / "logs"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local/share")
        d = pathlib.Path(base) / "packing-slips" / "logs"
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
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    if not first.startswith("#meta "):
        return None
    try:
        m = json.loads(first[6:])
        return Report(path, dt.datetime.fromisoformat(m["when"]), m["source"], bool(m["ok"]))
    except (ValueError, KeyError):
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_logstore.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: per-user log store with 30-day pruning"
```

---

### Task 5: Platform helpers

Everything OS-conditional that isn't binary resolution, isolated in one file so
it can be tested without a GUI.

**Files:**
- Create: `src/platform_bits.py`
- Test: `tests/test_platform_bits.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `open_for_print(path: pathlib.Path) -> None`
  - `reveal(path: pathlib.Path) -> None` — opens a folder in the file manager.
  - `desktop_entry_path() -> pathlib.Path`
  - `should_offer_desktop_entry() -> bool`
  - `install_desktop_entry(exe: str) -> pathlib.Path`
  - `remember_desktop_choice(yes: bool) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_platform_bits.py`:

```python
import os, pathlib, sys
import platform_bits as pb

def test_open_for_print_uses_startfile_on_windows(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "startfile", lambda p, verb=None: calls.append((p, verb)), raising=False)
    f = tmp_path / "a.pdf"; f.write_text("x")
    pb.open_for_print(f)
    assert calls == [(str(f), "print")]

def test_open_for_print_uses_xdg_on_linux(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(pb.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    f = tmp_path / "a.pdf"; f.write_text("x")
    pb.open_for_print(f)
    assert calls == [["xdg-open", str(f)]]

def test_reveal_opens_parent_directory(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(pb.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    pb.reveal(tmp_path)
    assert calls == [["xdg-open", str(tmp_path)]]

def test_desktop_entry_written_with_absolute_exec(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = pb.install_desktop_entry("/opt/packing-slips")
    text = p.read_text()
    assert "Exec=/opt/packing-slips %f" in text
    assert "Type=Application" in text
    assert p.name == "packing-slips.desktop"

def test_offer_is_remembered_after_decline(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pb.should_offer_desktop_entry() is True
    pb.remember_desktop_choice(False)
    assert pb.should_offer_desktop_entry() is False

def test_never_offer_on_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert pb.should_offer_desktop_entry() is False
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_platform_bits.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'platform_bits'`.

- [ ] **Step 3: Implement**

`src/platform_bits.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_platform_bits.py -v
```

Expected: all PASS.

- [ ] **Step 5: Delete the old hardcoded launcher and commit**

```bash
git rm "Run packing slips.desktop"
git add -A
git commit -m "feat: platform helpers for printing, revealing, and the Linux menu entry

Replaces the .desktop file that hardcoded one user's home directory."
```

---

### Task 6: The job runner (GUI logic without the GUI)

All the sequencing — build, verify, write the report, decide pass/fail — in a
headless class the GUI merely displays. This is what makes the flow testable
without tkinter.

**Files:**
- Create: `src/job.py`
- Test: `tests/test_job.py`

**Interfaces:**
- Consumes: `whatnot_slips.build/verify`, `logstore.write_report`.
- Produces:
  - `Job(src: pathlib.Path, dest: pathlib.Path, deep: bool = True)`
  - `Job.run(emit) -> Result`, where `emit(event: dict)` is called from the worker thread with dicts shaped `{"kind": "progress", "done": int, "total": int, "stage": str}`, `{"kind": "log", "line": str}`, or `{"kind": "done", "result": Result}`.
  - `Result` dataclass: `ok: bool`, `pages: int`, `checks: int`, `failures: int`, `report_path: pathlib.Path`, `dest: pathlib.Path | None`, `message: str`.
  - On failure `dest` is `None` and no file exists at the destination.

- [ ] **Step 1: Write the failing test**

`tests/test_job.py`:

```python
import pathlib, types
import pytest
import job as J

class FakeAudit:
    def __init__(self, failures=0, checks=3244):
        self.checks = checks
        self.fail = [("broken", "detail")] * failures
    def text(self, title):
        return f"\n{title}\n  assertions run : {self.checks}\n  failures       : {len(self.fail)}"

@pytest.fixture(autouse=True)
def logs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))

def test_success_writes_output_and_report(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    def fake_build(s, o, quiet=False, progress=None):
        pathlib.Path(o).write_text("pdf")
        if progress: progress(1, 1, "building slips")
        return (122, 123, 122)
    monkeypatch.setattr(J.ws, "build", fake_build)
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None: FakeAudit(0))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"] * 304)

    events = []
    res = J.Job(src, dest).run(events.append)
    assert res.ok is True
    assert res.pages == 304 and res.checks == 3244 and res.failures == 0
    assert res.dest == dest and dest.exists()
    assert res.report_path.exists()
    assert any(e["kind"] == "progress" for e in events)
    assert events[-1]["kind"] == "done"

def test_failure_removes_output_and_keeps_report(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    monkeypatch.setattr(J.ws, "build",
        lambda s, o, quiet=False, progress=None: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None: FakeAudit(14))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])

    res = J.Job(src, dest).run(lambda e: None)
    assert res.ok is False
    assert res.dest is None
    assert not dest.exists(), "a failed run must leave nothing to print"
    assert res.failures == 14
    assert "DO NOT PRINT" not in res.report_path.read_text()   # copy lives in the GUI

def test_exception_is_caught_and_logged(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    def boom(*a, **k): raise RuntimeError("ghostscript vanished")
    monkeypatch.setattr(J.ws, "build", boom)

    res = J.Job(src, dest).run(lambda e: None)
    assert res.ok is False
    assert res.dest is None
    assert "ghostscript vanished" in res.report_path.read_text()
    assert "Traceback" in res.report_path.read_text()
    assert "ghostscript vanished" in res.message
    assert "Traceback" not in res.message, "the window never shows a traceback"

def test_missing_binary_gets_an_actionable_message(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    def missing(*a, **k):
        raise FileNotFoundError(2, "No such file or directory", "gs")
    monkeypatch.setattr(J.ws, "build", missing)
    res = J.Job(src, tmp_path / "o.pdf").run(lambda e: None)
    assert res.ok is False
    assert "gs" in res.message
    assert "could not be started" in res.message

def test_unreadable_input_says_what_was_expected(tmp_path, monkeypatch):
    src = tmp_path / "notapdf.pdf"; src.write_text("hello")
    def bad(*a, **k):
        raise IndexError("list index out of range")
    monkeypatch.setattr(J.ws, "build", bad)
    res = J.Job(src, tmp_path / "o.pdf").run(lambda e: None)
    assert res.ok is False
    assert "Combined Labels + Packing Slips" in res.message
    assert "IndexError" not in res.message

def test_source_is_never_modified(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("original")
    dest = tmp_path / "out.pdf"
    monkeypatch.setattr(J.ws, "build",
        lambda s, o, quiet=False, progress=None: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None: FakeAudit(0))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    J.Job(src, dest).run(lambda e: None)
    assert src.read_text() == "original" and src.exists()
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_job.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'job'`.

- [ ] **Step 3: Implement**

`src/job.py`:

```python
"""One run, start to finish. Knows nothing about tkinter so it can be tested
without a display."""
import pathlib, traceback
from dataclasses import dataclass

import logstore
import whatnot_slips as ws

def _friendly(exc):
    """What to put in front of a person. The traceback goes to the log."""
    if isinstance(exc, FileNotFoundError):
        name = exc.filename or "a required program"
        return (f"{name} could not be started. This build looks incomplete — "
                f"please download it again.")
    if isinstance(exc, (IndexError, KeyError, ValueError, AttributeError)):
        return ("This PDF isn't a Whatnot Combined Labels + Packing Slips "
                "export, or its layout has changed.")
    if isinstance(exc, PermissionError):
        return "That location can't be written to. Try somewhere else."
    return f"{type(exc).__name__}: {exc}"

@dataclass
class Result:
    ok: bool
    pages: int
    checks: int
    failures: int
    report_path: pathlib.Path
    dest: pathlib.Path | None
    message: str

class Job:
    def __init__(self, src, dest, deep=True):
        self.src = pathlib.Path(src)
        self.dest = pathlib.Path(dest)
        self.deep = deep

    def run(self, emit):
        lines = [f"=== {self.src.name} -> {self.dest.name}"]

        def log(line):
            lines.append(line)
            emit({"kind": "log", "line": line})

        def progress(done, total, stage):
            emit({"kind": "progress", "done": done, "total": total, "stage": stage})

        try:
            n, nsl, nlb = ws.build(str(self.src), str(self.dest), quiet=True, progress=progress)
            log(f"built {self.dest.name}: {n} shipments, {nsl} slip pages, {nlb} labels")
            audit = ws.verify(str(self.src), str(self.dest), deep=self.deep, progress=progress)
            report = audit.text("AUDIT")
            for line in report.splitlines():
                log(line)
            pages = len(ws.pdf_pages(str(self.dest)))
            ok = not audit.fail
            if not ok:
                self._discard()
                log("nothing written — source left untouched")
            res = Result(ok, pages, audit.checks, len(audit.fail),
                         logstore.write_report("\n".join(lines), self.src.name, ok),
                         self.dest if ok else None,
                         "" if ok else f"{len(audit.fail)} checks failed")
        except Exception as exc:
            self._discard()
            lines.append("")
            lines.append(traceback.format_exc())
            res = Result(False, 0, 0, 0,
                         logstore.write_report("\n".join(lines), self.src.name, False),
                         None, _friendly(exc))
        emit({"kind": "done", "result": res})
        return res

    def _discard(self):
        """A failed run must leave nothing printable behind."""
        try:
            self.dest.unlink(missing_ok=True)
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_job.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: headless job runner with fail-safe output discard"
```

---

### Task 7: GUI shell — window, tabs, and the idle screen

**Files:**
- Create: `src/packing_gui.py`
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `job.Job`, `logstore`, `platform_bits`.
- Produces: `App(root)` with `App.show(name: str)` where name is one of `"idle" | "working" | "done" | "failed"`, `App.state -> str`, `App.tab(which: str)` for `"run" | "logs"`, and `App.pick_file(path=None)`.

Tests run headless via Tk's virtual display only if one exists; they skip
cleanly otherwise, so CI without a display still passes.

- [ ] **Step 1: Write the failing test**

`tests/test_gui.py`:

```python
import pytest

tk = pytest.importorskip("tkinter")

@pytest.fixture
def app():
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = packing_gui.App(root)
    yield a
    root.destroy()

def test_starts_idle_on_run_tab(app):
    assert app.state == "idle"
    assert app.current_tab == "run"

def test_window_title(app):
    assert app.root.title() == "Packing Slips"

def test_states_are_mutually_exclusive(app):
    for name in ("idle", "working", "done", "failed"):
        app.show(name)
        assert app.state == name
        visible = [n for n in ("idle", "working", "done", "failed")
                   if app.frames[n].winfo_manager()]
        assert visible == [name]

def test_tab_switching(app):
    app.tab("logs")
    assert app.current_tab == "logs"
    app.tab("run")
    assert app.current_tab == "run"

def test_failure_badges_the_logs_tab(app):
    app.mark_failure()
    assert app.badge_visible is True
    app.tab("logs")
    assert app.badge_visible is False
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_gui.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'packing_gui'`.

- [ ] **Step 3: Implement**

`src/packing_gui.py` — the shell only; later tasks fill the frames:

```python
"""The window. One state at a time, two tabs, nothing else."""
import pathlib, queue, sys, tkinter as tk
from tkinter import ttk, filedialog, messagebox

import job as jobmod
import logstore
import platform_bits

STATES = ("idle", "working", "done", "failed")

class App:
    def __init__(self, root):
        self.root = root
        root.title("Packing Slips")
        root.minsize(460, 300)
        self.queue = queue.Queue()
        self.state = "idle"
        self.current_tab = "run"
        self.badge_visible = False
        self.src = None
        self.result = None

        bar = ttk.Frame(root); bar.pack(fill="x")
        self.run_btn = ttk.Button(bar, text="Run", command=lambda: self.tab("run"))
        self.logs_btn = ttk.Button(bar, text="Logs", command=lambda: self.tab("logs"))
        self.run_btn.pack(side="left"); self.logs_btn.pack(side="left")

        self.panes = {
            "run": ttk.Frame(root),
            "logs": ttk.Frame(root),
        }
        self.frames = {name: ttk.Frame(self.panes["run"]) for name in STATES}
        self._build_idle(self.frames["idle"])

        self.panes["run"].pack(fill="both", expand=True)
        self.show("idle")

    # ---------------------------------------------------------- navigation
    def tab(self, which):
        self.current_tab = which
        for name, pane in self.panes.items():
            pane.pack_forget()
        self.panes[which].pack(fill="both", expand=True)
        if which == "logs":
            self.badge_visible = False
            self.logs_btn.configure(text="Logs")
            self.refresh_logs()

    def show(self, name):
        self.state = name
        for f in self.frames.values():
            f.pack_forget()
        self.frames[name].pack(fill="both", expand=True, padx=24, pady=20)

    def mark_failure(self):
        self.badge_visible = True
        self.logs_btn.configure(text="Logs ●")

    def refresh_logs(self):
        pass          # Task 9

    # ---------------------------------------------------------------- idle
    def _build_idle(self, f):
        ttk.Label(f, text="Drop a Whatnot export here",
                  font=("TkDefaultFont", 12)).pack(pady=(28, 14))
        ttk.Button(f, text="Choose file…", command=self.pick_file).pack()
        ttk.Label(f, text="Combined Labels + Packing Slips, straight from Whatnot.",
                  foreground="#6a6d73").pack(pady=(16, 0))

    def pick_file(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Choose a Whatnot export",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        self.src = pathlib.Path(path)
        self.start()

    def start(self):
        pass          # Task 8

def main():
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:                 # dropped on the icon
        app.pick_file(sys.argv[1])
    root.mainloop()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_gui.py -v
.venv/bin/python src/packing_gui.py     # eyeball it, then close the window
```

Expected: tests PASS; a small window appears titled "Packing Slips".

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: GUI shell with Run/Logs tabs and idle screen"
```

---

### Task 8: Save-first flow, worker thread, and progress

**Files:**
- Modify: `src/packing_gui.py`
- Test: `tests/test_gui_flow.py`

**Interfaces:**
- Consumes: Task 7's `App`, Task 6's `Job`.
- Produces: `App.start()` (asks for the destination, then spawns the worker), `App.pump()` (drains the queue on the Tk loop), `App.default_name() -> str` returning `YYYY-MM-DD-slips.pdf`.

- [ ] **Step 1: Write the failing test**

`tests/test_gui_flow.py`:

```python
import datetime as dt, pathlib, threading, time
import pytest

tk = pytest.importorskip("tkinter")

@pytest.fixture
def app(tmp_path, monkeypatch):
    import packing_gui
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = packing_gui.App(root)
    yield a
    root.destroy()

def test_default_name_is_dated(app):
    assert app.default_name() == dt.date.today().strftime("%Y-%m-%d-slips.pdf")

def test_cancelling_save_returns_to_idle(app, tmp_path, monkeypatch):
    import packing_gui
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename", lambda **kw: "")
    app.pick_file(str(tmp_path / "in.pdf"))
    assert app.state == "idle", "cancelling must cost nothing"

def test_save_dialog_comes_before_work(app, tmp_path, monkeypatch):
    import packing_gui
    order = []
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename",
                        lambda **kw: (order.append("save"), str(tmp_path / "o.pdf"))[1])
    monkeypatch.setattr(packing_gui.jobmod.Job, "run",
                        lambda self, emit: order.append("work"))
    app.pick_file(str(tmp_path / "in.pdf"))
    for _ in range(50):
        if "work" in order: break
        app.root.update(); time.sleep(0.02)
    assert order == ["save", "work"]

def test_unwritable_destination_reopens_the_dialog(app, tmp_path, monkeypatch):
    """Spec: a bad save location re-asks rather than failing 90 seconds later."""
    import packing_gui
    asked = []
    bad = tmp_path / "nope" / "deep" / "o.pdf"      # parent does not exist
    good = tmp_path / "o.pdf"
    def fake_save(**kw):
        asked.append(1)
        return str(bad) if len(asked) == 1 else str(good)
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename", fake_save)
    monkeypatch.setattr(packing_gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(packing_gui.jobmod.Job, "run", lambda self, emit: None)
    app.pick_file(str(tmp_path / "in.pdf"))
    assert len(asked) == 2, "should have re-asked once"
    assert app.state == "working"

def test_progress_events_update_the_bar(app):
    app.show("working")
    app.queue.put({"kind": "progress", "done": 84, "total": 152, "stage": "building slips"})
    app.pump()
    assert app.progress_text.get() == "rendering 84/152"
    assert app.stage_text.get() == "building slips…"

def test_done_event_switches_to_result(app, tmp_path):
    import job
    r = job.Result(True, 304, 3743, 0, tmp_path / "r.log", tmp_path / "o.pdf", "")
    app.queue.put({"kind": "done", "result": r})
    app.pump()
    assert app.state == "done"
    assert "304" in app.stats_text.get()
    assert "3,743" in app.stats_text.get()

def test_failed_result_badges_and_shows_failure(app, tmp_path):
    import job
    r = job.Result(False, 0, 3743, 14, tmp_path / "r.log", None, "14 checks failed")
    app.queue.put({"kind": "done", "result": r})
    app.pump()
    assert app.state == "failed"
    assert app.badge_visible is True

def test_no_tk_calls_from_worker_thread(app, tmp_path, monkeypatch):
    """The worker may only touch the queue. If it touched Tk, Tk would
    usually crash; assert the discipline directly instead."""
    import packing_gui
    seen = {}
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename", lambda **kw: str(tmp_path / "o.pdf"))
    def fake_run(self, emit):
        seen["thread"] = threading.current_thread() is not threading.main_thread()
        emit({"kind": "progress", "done": 1, "total": 1, "stage": "building slips"})
    monkeypatch.setattr(packing_gui.jobmod.Job, "run", fake_run)
    app.pick_file(str(tmp_path / "in.pdf"))
    for _ in range(50):
        if "thread" in seen: break
        app.root.update(); time.sleep(0.02)
    assert seen["thread"] is True
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_gui_flow.py -v
```

Expected: FAIL — `App` has no attribute `default_name`.

- [ ] **Step 3: Implement**

In `src/packing_gui.py`, add `import datetime as dt, os, threading` at the top, build
the working/done/failed frames in `__init__` (call the three builders below after
`self._build_idle(...)`), and replace the stub `start`:

```python
    # ------------------------------------------------------------- working
    def _build_working(self, f):
        self.file_text = tk.StringVar(value="")
        self.progress_text = tk.StringVar(value="")
        self.stage_text = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.file_text,
                  font=("TkDefaultFont", 10, "bold")).pack(pady=(28, 12))
        self.bar = ttk.Progressbar(f, mode="determinate", length=380)
        self.bar.pack()
        ttk.Label(f, textvariable=self.progress_text,
                  foreground="#6a6d73").pack(pady=(10, 2))
        ttk.Label(f, textvariable=self.stage_text, foreground="#6a6d73").pack()

    def _build_done(self, f):
        self.stats_text = tk.StringVar(value="")
        ttk.Label(f, text="✓  Ready to print", foreground="#1f7a3f",
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, textvariable=self.stats_text, foreground="#6a6d73",
                  justify="center").pack()
        row = ttk.Frame(f); row.pack(pady=16)
        ttk.Button(row, text="Print", command=self.do_print).pack(side="left", padx=5)
        ttk.Button(row, text="Do another", command=self.reset).pack(side="left", padx=5)
        ttk.Button(f, text="See the full report",
                   command=lambda: self.tab("logs")).pack()

    def _build_failed(self, f):
        self.fail_text = tk.StringVar(value="")
        ttk.Label(f, text="✗  DO NOT PRINT", foreground="#b3261e",
                  font=("TkDefaultFont", 13, "bold")).pack(pady=(26, 10))
        ttk.Label(f, text="This export failed its checks. Nothing was saved.",
                  justify="center").pack()
        ttk.Label(f, textvariable=self.fail_text, foreground="#6a6d73").pack(pady=(6, 0))
        row = ttk.Frame(f); row.pack(pady=16)
        ttk.Button(row, text="See what failed",
                   command=lambda: self.tab("logs")).pack(side="left", padx=5)
        ttk.Button(row, text="Do another", command=self.reset).pack(side="left", padx=5)

    # ----------------------------------------------------------------- run
    def default_name(self):
        return dt.date.today().strftime("%Y-%m-%d-slips.pdf")

    def ask_destination(self):
        """Ask until we get somewhere writable, or the user gives up. Checking
        now costs a second; checking after the build costs ninety."""
        while True:
            dest = filedialog.asksaveasfilename(
                title="Save print-ready PDF as…",
                initialfile=self.default_name(),
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")])
            if not dest:
                return None               # cancelled — costs nothing
            d = pathlib.Path(dest)
            if d.parent.is_dir() and os.access(d.parent, os.W_OK):
                return d
            messagebox.showerror(
                "Can't save there",
                f"{d.parent} can't be written to. Choose another folder.")

    def start(self):
        dest = self.ask_destination()
        if dest is None:
            self.show("idle")
            return
        self.file_text.set(self.src.name)
        self.progress_text.set("")
        self.stage_text.set("starting…")
        self.bar.configure(value=0, maximum=100)
        self.log_lines = []
        self.show("working")
        job = jobmod.Job(self.src, dest)
        threading.Thread(target=job.run, args=(self.queue.put,), daemon=True).start()
        self.root.after(100, self.pump)

    def pump(self):
        while True:
            try:
                ev = self.queue.get_nowait()
            except queue.Empty:
                break
            kind = ev["kind"]
            if kind == "progress":
                done, total, stage = ev["done"], ev["total"], ev["stage"]
                self.bar.configure(maximum=total, value=done)
                verb = "rendering" if stage == "building slips" else "checking"
                self.progress_text.set(f"{verb} {done}/{total}")
                self.stage_text.set(f"{stage}…")
            elif kind == "log":
                self.log_lines.append(ev["line"])
                self.append_log(ev["line"])
            elif kind == "done":
                self.finish(ev["result"])
                return
        if self.state == "working":
            self.root.after(100, self.pump)

    def finish(self, result):
        self.result = result
        if result.ok:
            self.stats_text.set(f"{result.pages} pages\n{result.checks:,} checks passed")
            self.show("done")
        else:
            self.fail_text.set(result.message)
            self.mark_failure()
            self.show("failed")
        self.refresh_logs()

    def do_print(self):
        if self.result and self.result.dest:
            platform_bits.open_for_print(self.result.dest)

    def reset(self):
        self.src = self.result = None
        self.show("idle")

    def append_log(self, line):
        pass          # Task 9
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_gui_flow.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: save-first flow, worker thread, and live progress"
```

---

### Task 9: Logs tab

**Files:**
- Modify: `src/packing_gui.py`
- Test: `tests/test_gui_logs.py`

**Interfaces:**
- Consumes: `logstore.list_reports/label/prune`, Task 8's `append_log` hook.
- Produces: `App.refresh_logs()`, `App.append_log(line)`, `App.log_text() -> str`, `App.select_report(index: int)`, `App.save_report()`.

- [ ] **Step 1: Write the failing test**

`tests/test_gui_logs.py`:

```python
import datetime as dt
import pytest

tk = pytest.importorskip("tkinter")

@pytest.fixture
def app(tmp_path, monkeypatch):
    import packing_gui
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = packing_gui.App(root)
    yield a
    root.destroy()

def test_live_lines_appear_in_the_pane(app):
    app.show("working")
    app.log_lines = []
    app.append_log("built out.pdf: 122 shipments")
    app.tab("logs")
    assert "built out.pdf: 122 shipments" in app.log_text()

def test_past_runs_listed_newest_first(app):
    import logstore
    logstore.write_report("old", "old.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    logstore.write_report("new", "new.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    app.tab("logs")
    assert "new.pdf" in app.picker["values"][0]
    assert "old.pdf" in app.picker["values"][1]

def test_selecting_a_past_run_shows_its_text(app):
    import logstore
    logstore.write_report("the old report body", "old.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.tab("logs")
    app.select_report(0)
    assert "the old report body" in app.log_text()

def test_meta_line_is_not_shown_to_the_user(app):
    import logstore
    logstore.write_report("body", "x.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.tab("logs")
    app.select_report(0)
    assert "#meta" not in app.log_text()

def test_save_report_writes_selected_text(app, tmp_path, monkeypatch):
    import packing_gui, logstore
    logstore.write_report("body to export", "x.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    target = tmp_path / "sent.txt"
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename", lambda **kw: str(target))
    app.tab("logs"); app.select_report(0); app.save_report()
    assert "body to export" in target.read_text()

def test_prune_runs_at_startup(tmp_path, monkeypatch):
    import logstore, packing_gui
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    logstore.write_report("ancient", "a.pdf", True, dt.datetime.now() - dt.timedelta(days=90))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    packing_gui.App(root)
    assert logstore.list_reports() == []
    root.destroy()
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_gui_logs.py -v
```

Expected: FAIL — `App` has no attribute `log_text`.

- [ ] **Step 3: Implement**

In `__init__`, after building the run pane, add `logstore.prune(30)` and
`self._build_logs(self.panes["logs"])`. Then:

```python
    # ---------------------------------------------------------------- logs
    def _build_logs(self, pane):
        top = ttk.Frame(pane); top.pack(fill="x", padx=12, pady=(10, 6))
        self.picker = ttk.Combobox(top, state="readonly", values=[])
        self.picker.pack(fill="x")
        self.picker.bind("<<ComboboxSelected>>",
                         lambda e: self.select_report(self.picker.current()))

        self.logbox = tk.Text(pane, height=10, wrap="word", font=("TkFixedFont", 9))
        self.logbox.pack(fill="both", expand=True, padx=12)
        self.logbox.configure(state="disabled")

        foot = ttk.Frame(pane); foot.pack(fill="x", padx=12, pady=8)
        ttk.Button(foot, text="Save report…", command=self.save_report).pack(side="right")
        ttk.Button(foot, text="Open folder",
                   command=lambda: platform_bits.reveal(logstore.log_dir())).pack(side="right", padx=6)

    def log_text(self):
        return self.logbox.get("1.0", "end-1c")

    def _set_log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.insert("1.0", text)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def append_log(self, line):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def refresh_logs(self):
        self.reports = logstore.list_reports()
        labels = [logstore.label(r) for r in self.reports]
        if self.state == "working":
            labels = ["This run"] + labels
        self.picker.configure(values=labels)
        if labels:
            self.picker.current(0)

    def select_report(self, index):
        if self.state == "working" and index == 0:
            self._set_log("\n".join(getattr(self, "log_lines", [])))
            return
        offset = 1 if self.state == "working" else 0
        r = self.reports[index - offset]
        body = r.path.read_text(encoding="utf-8").splitlines()
        if body and body[0].startswith("#meta "):
            body = body[1:]
        self._set_log("\n".join(body))

    def save_report(self):
        target = filedialog.asksaveasfilename(
            title="Save report", initialfile="packing-slips-report.txt",
            defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if target:
            pathlib.Path(target).write_text(self.log_text(), encoding="utf-8")
```

Also change `refresh_logs`'s stub call in `tab()` — it is already called there.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest -v
```

Expected: every test PASSes, parity included.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: logs tab with live tail, past runs, and save report"
```

---

### Task 10: First-run menu entry offer (Linux)

**Files:**
- Modify: `src/packing_gui.py`
- Test: `tests/test_gui_desktop.py`

**Interfaces:**
- Consumes: `platform_bits.should_offer_desktop_entry/install_desktop_entry/remember_desktop_choice`.
- Produces: `App.maybe_offer_desktop_entry()` — called once from `main()`, never from `__init__` (so tests constructing `App` never trigger a dialog).

- [ ] **Step 1: Write the failing test**

`tests/test_gui_desktop.py`:

```python
import pytest
tk = pytest.importorskip("tkinter")

@pytest.fixture
def app(tmp_path, monkeypatch):
    import packing_gui
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield packing_gui.App(root)
    root.destroy()

def test_accepting_installs_entry(app, monkeypatch, tmp_path):
    import packing_gui, platform_bits, sys
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(sys, "executable", "/opt/packing-slips")
    app.maybe_offer_desktop_entry()
    assert platform_bits.desktop_entry_path().exists()

def test_declining_is_remembered(app, monkeypatch):
    import packing_gui, platform_bits
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: False)
    app.maybe_offer_desktop_entry()
    assert not platform_bits.desktop_entry_path().exists()
    monkeypatch.undo()
    assert platform_bits.should_offer_desktop_entry() is False

def test_not_offered_when_helper_says_no(app, monkeypatch):
    import packing_gui, platform_bits
    asked = []
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: False)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno",
                        lambda *a, **k: asked.append(1) or True)
    app.maybe_offer_desktop_entry()
    assert asked == []
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
.venv/bin/pytest tests/test_gui_desktop.py -v
```

Expected: FAIL — `App` has no attribute `maybe_offer_desktop_entry`.

- [ ] **Step 3: Implement**

```python
    def maybe_offer_desktop_entry(self):
        if not platform_bits.should_offer_desktop_entry():
            return
        yes = messagebox.askyesno(
            "Add to your applications menu?",
            "Add Packing Slips to your applications menu, so you can find it "
            "without hunting for this file?\n\nYou'll only be asked once.")
        platform_bits.remember_desktop_choice(yes)
        if yes:
            platform_bits.install_desktop_entry(sys.executable)
```

And in `main()`, after constructing `App` and before `mainloop()`:

```python
    app.maybe_offer_desktop_entry()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: offer a Linux menu entry once on first run"
```

---

### Task 11: PyInstaller bundle for Linux, plus a clean-room smoke test

**Files:**
- Create: `packaging/collect_binaries.py`
- Create: `packaging/packing.spec`
- Create: `packaging/smoke_test.sh`
- Modify: `.gitignore` (add `build/`, `dist/`, `packaging/bin/`)

**Interfaces:**
- Consumes: everything above.
- Produces: `dist/packing-slips` (Linux single-file executable) and a smoke test proving it runs with no poppler or ghostscript on the system.

- [ ] **Step 1: Write the binary collector**

`packaging/collect_binaries.py`:

```python
"""Stage gs/pdftotext/pdfimages and their shared libraries into packaging/bin/
so PyInstaller can carry them. Run before building on Linux."""
import pathlib, shutil, subprocess, sys

TOOLS = ["gs", "pdftotext", "pdfimages"]
OUT = pathlib.Path(__file__).parent / "bin"

def libs_of(binary):
    out = subprocess.run(["ldd", binary], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        parts = line.split()
        for p in parts:
            if p.startswith("/") and pathlib.Path(p).is_file():
                yield pathlib.Path(p)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for tool in TOOLS:
        path = shutil.which(tool)
        if not path:
            sys.exit(f"missing {tool} — install poppler-utils and ghostscript")
        shutil.copy2(path, OUT / tool)
        for lib in libs_of(path):
            target = OUT / lib.name
            if not target.exists():
                shutil.copy2(lib, target)
    print(f"staged {len(list(OUT.iterdir()))} files into {OUT}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the PyInstaller spec**

`packaging/packing.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
import pathlib, sys
root = pathlib.Path(SPECPATH).parent
binaries = [(str(p), "bin") for p in (root / "packaging" / "bin").glob("*")]

a = Analysis(
    [str(root / "src" / "packing_gui.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=[],
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["pytest", "numpy", "matplotlib"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="packing-slips",
    console=False,
    upx=False,
)
```

- [ ] **Step 3: Build it**

```bash
cd "/home/mhamida/Desktop/Projects/Packing Logistics"
.venv/bin/python packaging/collect_binaries.py
.venv/bin/pyinstaller --clean --noconfirm packaging/packing.spec
ls -lh dist/packing-slips
```

Expected: a single executable, roughly 70–90 MB.

- [ ] **Step 4: Write and run the clean-room smoke test**

The point is to prove the bundle carries its own Ghostscript and Poppler, so it
must run somewhere those are *not* installed. `packaging/smoke_test.sh`:

```bash
#!/usr/bin/env bash
# Prove dist/packing-slips works with no system poppler/ghostscript.
# Requires docker. Usage: packaging/smoke_test.sh /path/to/export.pdf
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: smoke_test.sh EXPORT.pdf}"

docker run --rm \
  -v "$PWD/dist:/app:ro" -v "$(realpath "$SRC"):/in.pdf:ro" \
  ubuntu:22.04 \
  bash -c '
    set -e
    command -v gs        && { echo "FAIL: gs present, not a clean room"; exit 1; } || true
    command -v pdftotext && { echo "FAIL: poppler present"; exit 1; } || true
    /app/packing-slips --selftest /in.pdf
  '
echo "SMOKE OK"
```

This needs a headless entry point, since there is no display in the container.
Add to `src/packing_gui.py` in `main()`, before creating the window:

```python
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "out.pdf"
            res = jobmod.Job(sys.argv[2], out, deep=False).run(lambda e: None)
        print(f"selftest: ok={res.ok} checks={res.checks} failures={res.failures}")
        sys.exit(0 if res.ok else 1)
```

Run it:

```bash
chmod +x packaging/smoke_test.sh
packaging/smoke_test.sh .packing/archive/2026-09-09-show.pdf
```

Expected: `selftest: ok=True checks=... failures=0` then `SMOKE OK`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "build: PyInstaller bundle for Linux with a clean-room smoke test"
```

---

### Task 12: CI, release, and documentation

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `packaging/fetch_windows_binaries.ps1`
- Modify: `README.md`
- Create: `NOTICE.md`

**Interfaces:**
- Consumes: Task 11's spec and collector.
- Produces: a GitHub Release on a `v*` tag carrying `packing-slips` (Linux) and `packing-slips.exe` (Windows).

- [ ] **Step 1: Write the Windows binary fetcher**

`packaging/fetch_windows_binaries.ps1`:

```powershell
# Stage gswin64c.exe, its DLL, and poppler's tools into packaging\bin
$ErrorActionPreference = "Stop"
$out = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$gsUrl = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe"
$popUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"

Invoke-WebRequest $gsUrl -OutFile "$env:TEMP\gs.exe"
Start-Process "$env:TEMP\gs.exe" -ArgumentList "/S","/D=$env:TEMP\gs" -Wait
Copy-Item "$env:TEMP\gs\bin\gswin64c.exe" $out
Copy-Item "$env:TEMP\gs\bin\gsdll64.dll"  $out

Invoke-WebRequest $popUrl -OutFile "$env:TEMP\poppler.zip"
Expand-Archive "$env:TEMP\poppler.zip" -DestinationPath "$env:TEMP\poppler" -Force
Copy-Item "$env:TEMP\poppler\poppler-24.08.0\Library\bin\*" $out -Recurse -Force

Get-ChildItem $out | Select-Object Name, Length
```

Pin these versions deliberately; bumping them is a reviewed change, not a drift.

- [ ] **Step 2: Write the workflow**

`.github/workflows/release.yml`:

```yaml
name: release
on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  linux:
    runs-on: ubuntu-22.04     # oldest runner: keeps the glibc floor low
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: sudo apt-get update && sudo apt-get install -y poppler-utils ghostscript python3-tk
      - run: pip install pyinstaller pillow pytest
      - run: pytest -v            # parity tests skip without PACKING_TEST_PDF
      - run: python packaging/collect_binaries.py
      - run: pyinstaller --clean --noconfirm packaging/packing.spec
      - uses: actions/upload-artifact@v4
        with: { name: packing-slips-linux, path: dist/packing-slips }

  windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install pyinstaller pillow pytest
      - run: pytest -v
      - run: powershell -File packaging/fetch_windows_binaries.ps1
      - run: pyinstaller --clean --noconfirm packaging/packing.spec
      - uses: actions/upload-artifact@v4
        with: { name: packing-slips-windows, path: dist/packing-slips.exe }

  release:
    needs: [linux, windows]
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/download-artifact@v4
        with: { path: artifacts }
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            artifacts/packing-slips-linux/packing-slips
            artifacts/packing-slips-windows/packing-slips.exe
          body: |
            Download one file and double-click it. Nothing to install.

            - **Windows:** `packing-slips.exe`. Windows will warn that it is
              unsigned — choose **More info → Run anyway**.
            - **Linux:** `packing-slips`. Run `chmod +x packing-slips` once.
              Needs glibc 2.35 or newer (Ubuntu 22.04+).
```

- [ ] **Step 3: Write the licence notice**

`NOTICE.md`:

```markdown
# Third-party software in the downloadable builds

The single-file builds on the Releases page bundle:

- **Ghostscript** (AGPL-3.0) — https://www.ghostscript.com/
- **Poppler** utilities `pdftotext`, `pdfimages` (GPL-2.0) — https://poppler.freedesktop.org/
- **Python** (PSF licence) and **Pillow** (MIT-CMU)

Because Ghostscript is AGPL, the complete source of this program is published
at https://github.com/mhamida292/LabelCondense, which satisfies the licence for
anyone who receives a build.
```

- [ ] **Step 4: Rewrite the README's opening**

Replace the top of `README.md` (everything before `## Daily use`) with a
download-first section, and keep the existing "Under the hood" and "Design
notes" sections untouched:

```markdown
# Packing slips

Rebuilds the Whatnot **Combined Labels + Packing Slips** export so repeated
products collapse onto one line — keeping **every `#N` and its price** — and
re-interleaves them with the original shipping labels.

## Download

Go to the [Releases page](https://github.com/mhamida292/LabelCondense/releases)
and get one file. There is nothing to install.

| | |
|---|---|
| **Windows** | `packing-slips.exe` — double-click it. The first time, Windows says "Windows protected your PC" because the file is not code-signed. Click **More info**, then **Run anyway**. |
| **Linux** | `packing-slips` — run `chmod +x packing-slips` once, then double-click. Needs Ubuntu 22.04 or newer. |

Then: drag a Whatnot export onto the icon (or open the app and click
**Choose file…**), choose where to save, wait about 90 seconds, and print.

**If it says DO NOT PRINT, don't print it.** Nothing was saved. Open the
**Logs** tab, click **Save report…**, and send that file over.

The download is large (~100 MB) because it carries its own copy of Ghostscript
and Poppler, so nothing has to be installed separately. See [NOTICE.md](NOTICE.md).
```

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -v
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('workflow yaml ok')"
git add -A
git commit -m "ci: build and release Windows and Linux bundles; document the download"
git push -u origin main
```

Then tag a first release and watch it build:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Expected: both jobs green, two files attached to the Release.

---

## Post-plan verification

Before calling this done, confirm all of the following and paste the output:

```bash
.venv/bin/pytest -v                                        # every test
PACKING_TEST_PDF=.packing/archive/2026-09-09-show.pdf .venv/bin/pytest -v
./run.sh --fast                                            # CLI still works
packaging/smoke_test.sh .packing/archive/2026-09-09-show.pdf
```

**Known to be unverifiable here:** the Windows `.exe`. CI builds it, but nobody
has double-clicked it on real Windows. Do not claim it works — say it is built
and untested, and expect one round of remote debugging, most likely the
Ghostscript DLL or a missing Visual C++ runtime.
