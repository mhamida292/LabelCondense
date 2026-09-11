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
