# Cross-platform GUI — design

Date: 2026-09-11
Status: approved, ready for implementation planning

## Purpose

Let someone who has never used git, a terminal, or Python turn a Whatnot
export into a print-ready PDF by downloading one file and double-clicking it.
Windows and Linux both.

Today the tool requires cloning a repo, installing `poppler-utils` and
`ghostscript`, and running `./run.sh` from a shell. On Windows it does not run
at all: `run.sh` is bash with GNU-specific `stat -c` and `find -mtime`, the
launcher is a KDE `.desktop` file invoking `konsole`, and the renderer shells
out to `gs`, which on Windows is named `gswin64c.exe`.

## Scope

**In:** a tkinter GUI, per-OS single-file bundles containing Ghostscript and
Poppler, a tagged GitHub Release carrying both, and the minimum changes to
`whatnot_slips.py` needed to run frozen.

**Out:** replacing Ghostscript with a pure-Python PDF writer; macOS; any change
to the rendering or audit logic; any change to CLI behaviour.

## Constraints

- `whatnot_slips.py` emits raw PostScript and hands it to Ghostscript
  (`whatnot_slips.py:311-320`). Ghostscript is the output stage, not a
  swappable detail. It must be bundled, not replaced.
- Bundling Ghostscript (AGPL) and Poppler (GPL) means the distributed artifact
  is copyleft. The repo is already public, which satisfies this. The README
  must carry the notice and link to the sources.
- A full run takes roughly 90 seconds. The GUI must never appear frozen.
- The existing audit is the safety net for this whole change. CLI behaviour and
  audit output must be byte-identical before and after.

## User experience

One window, one state at a time, two tabs: **Run** and **Logs**.

### Run tab

1. **Idle** — "Drop a Whatnot export here" over a `Choose file…` button.
   Dropping a file on the app icon skips straight to step 2.
2. **Save As** — appears *before* processing, pre-filled `YYYY-MM-DD-slips.pdf`.
   Deliberately up front: cancelling then costs nothing, and nobody is left
   hunting for a folder with a finished job on screen.
3. **Working** — filename, progress bar, live counter (`rendering 84/152`, then
   the audit count), and a one-line stage description.
4. **Done** — green `✓ Ready to print`, page count, checks passed, and two
   buttons: `Print` (opens the PDF in the system viewer with the print dialog)
   and `Do another`. A `See the full report` link switches to Logs.
5. **Failed** — red `✗ DO NOT PRINT`, "This export failed its checks. Nothing
   was saved.", and `See what failed` (switches to Logs) plus `Do another`.

No partial output is ever written, matching `run.sh`'s `rm -f "$out"` on
failure. The source file is never moved or modified.

### Logs tab

- Live-tails the current run's report as it is produced.
- A dropdown of past runs, pruned at 30 days, matching `run.sh`'s `KEEP_DAYS`.
- `FAIL` lines rendered in red; a failure puts a red dot on the tab.
- `Save report…` writes the selected report wherever the user chooses. This
  replaces the README's "send me `.packing/logs/<date>.log`".
- `Open folder` reveals the logs directory in the file manager.

Logs contain buyer usernames on failure lines. They are written to a per-user
application data directory — `%LOCALAPPDATA%\PackingSlips\logs` on Windows,
`~/.local/share/packing-slips/logs` on Linux — never inside the bundle, and
never uploaded.

## Architecture

Three files, each with one job:

| Unit | Responsibility | Depends on |
|---|---|---|
| `whatnot_slips.py` | build + audit. Unchanged logic. | poppler, ghostscript, Pillow |
| `packing_gui.py` | window, state machine, worker thread, log pane | `whatnot_slips`, tkinter |
| `packing.spec` | PyInstaller recipe: what to freeze, which binaries to carry | PyInstaller |

The GUI **imports** `whatnot_slips` and calls `build()` directly. It does not
shell out to itself — a frozen executable re-invoking itself is a known source
of recursion bugs, and a direct call gives real exceptions and real progress.

### Changes to `whatnot_slips.py`

Two additions, both no-ops for the CLI path:

**1. A binary resolver.** Three call sites (`:93`, `:274`, `:314`) change from a
bare name to `_bin(name)`:

```python
def _bin(name):
    base = getattr(sys, '_MEIPASS', None)      # set only when frozen
    if not base:
        return name                            # CLI: unchanged, use PATH
    exe = {'gs': 'gswin64c.exe'}.get(name, name + '.exe') if os.name == 'nt' else name
    return os.path.join(base, 'bin', exe)
```

**2. A progress callback.** `build()` currently prints progress only when stderr
is a tty (`:308`), so under the GUI it would run silently for 90 seconds. Add an
optional `progress=None` parameter, called with `(done, total, stage)`. The
existing tty print stays as the default when no callback is given.

A shared `_run()` wrapper around `subprocess.run` adds
`creationflags=CREATE_NO_WINDOW` on Windows. Without it, a windowed `.exe`
flashes a console for every one of ~150 subprocess calls.

### Threading

`build()` runs on a worker thread. It reports progress by putting messages on a
`queue.Queue`; the Tk main loop drains the queue on a ~100 ms `after()` timer.
No Tk call is ever made from the worker thread — tkinter is not thread-safe.
Cancellation is out of scope for v1; the window stays responsive and the user
can close it.

### Platform-specific surface

Everything OS-dependent is confined to these four points:

| Concern | Windows | Linux |
|---|---|---|
| Ghostscript binary | `gswin64c.exe` + `gsdll64.dll` | `gs` + libs |
| Console flash | `CREATE_NO_WINDOW` | n/a |
| Open finished PDF | `os.startfile(path, 'print')` | `xdg-open` |
| Drop on icon | `argv[1]`, native | `.desktop` with `Exec=… %f` |

## Packaging and distribution

PyInstaller one-file build per OS, carrying Ghostscript and Poppler binaries
under `bin/` inside the bundle.

- **Windows:** official Ghostscript release binaries; the community Poppler
  for Windows build. Output: one `.exe`, roughly 80–110 MB.
- **Linux:** `gs`, `pdftotext`, `pdfimages` and their shared libraries from
  apt. Output: one binary, roughly 70–90 MB.

PyInstaller cannot cross-compile, so GitHub Actions builds each on its own
runner (`windows-latest`, and `ubuntu-22.04` to keep the glibc floor low) on a
version tag, attaching both to a GitHub Release. The Release page becomes the
link to send to a non-technical user.

The Linux `.desktop` launcher's hardcoded `/home/mhamida/...` path goes away.
Instead, on first run the Linux binary offers once to add itself to the
applications menu, writing `~/.local/share/applications/packing-slips.desktop`
with `Exec=<absolute path to this binary> %f` resolved from `sys.executable`.
Declining is remembered and never asked again. No installer, no sudo.

## Error handling

| Failure | Behaviour |
|---|---|
| Audit fails | Red DO NOT PRINT screen. No output written. Report kept. |
| Input is not a Whatnot export | Plain message naming what was expected. No traceback. |
| Save location unwritable | Re-open the Save dialog with the error shown. |
| Bundled binary missing / won't start | Named, actionable message, written to the log. |
| Unexpected exception | Caught at the worker boundary, full traceback to the log, one-line summary on screen. |

The GUI never shows a raw Python traceback in the main window. Tracebacks go to
the log, which the user can send with `Save report…`.

## Testing

- **Parity is the primary test:** the same export processed by the current CLI
  and by the refactored module must produce byte-identical output and an
  identical audit count. This is what protects the 3,244-assertion audit
  through the refactor.
- `_bin()` unit-tested for frozen and unfrozen, Windows and POSIX.
- Progress callback unit-tested for monotonic counts reaching the total.
- GUI state machine tested headlessly where practical: idle → picked → working
  → done/failed, and that no output file exists after a failure.
- The Linux bundle is smoke-tested here, on a clean container without poppler
  or ghostscript installed, to prove the bundling actually works.
- **The Windows bundle cannot be verified on this machine.** CI can build it;
  it is unverified until someone double-clicks it on real Windows. One round of
  remote debugging should be assumed, most likely the Ghostscript DLL or a
  missing Visual C++ runtime.

## Risks

1. **Windows is built blind.** Mitigated by CI reproducibility and by keeping
   the failure path loud and logged.
2. **Linux glibc floor.** A binary built on a newer runner won't start on an
   older distro. Mitigated by building on the oldest supported runner and
   stating the floor in the README.
3. **Refactor touches audited code.** Mitigated by the parity test above and by
   keeping both changes no-ops on the CLI path.
4. **Bundle size.** ~100 MB is large for a download but is the direct cost of
   the "zero setup" decision, which was made deliberately.
5. **Unsigned executable.** Windows SmartScreen will warn on first run. The
   README must show the warning and say to click through it. Code signing is
   out of scope.

## Out of scope for v1

In-window drag-and-drop (needs `tkinterdnd2`, a compiled dependency that is
awkward under PyInstaller — drop-on-icon covers the gesture for free); macOS;
batch processing of several files at once; cancelling a run in progress; code
signing; auto-update.
