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
    report_path: pathlib.Path | None
    dest: pathlib.Path | None
    message: str

class Job:
    def __init__(self, src, dest, deep=True, brand=None):
        self.src = pathlib.Path(src)
        self.dest = pathlib.Path(dest)
        self.deep = deep
        self.brand = brand

    def run(self, emit):
        lines = [f"=== {self.src.name} -> {self.dest.name}"]

        def log(line):
            lines.append(line)
            emit({"kind": "log", "line": line})

        def progress(done, total, stage):
            emit({"kind": "progress", "done": done, "total": total, "stage": stage})

        for note in (self.brand.notes if self.brand else []):
            log(f"branding: {note}")

        try:
            n, nsl, nlb = ws.build(str(self.src), str(self.dest), quiet=True,
                                   progress=progress, brand=self.brand)
            log(f"built {self.dest.name}: {n} shipments, {nsl} slip pages, {nlb} labels")
            audit = ws.verify(str(self.src), str(self.dest), deep=self.deep,
                              progress=progress, brand=self.brand)
            report = audit.text("AUDIT")
            for line in report.splitlines():
                log(line)
            pages = len(ws.pdf_pages(str(self.dest)))
            ok = not audit.fail

            discard_warning = ""
            if not ok:
                if self._discard():
                    log("nothing written — source left untouched")
                else:
                    discard_warning = self._discard_warning()
                    log(discard_warning)

            report_path, report_err = self._write_report("\n".join(lines), ok)
            report_note = f"the report could not be saved: {report_err}" if report_err else ""

            if ok:
                message = report_note
            else:
                message = discard_warning or report_note or f"{len(audit.fail)} checks failed"

            res = Result(ok, pages, audit.checks, len(audit.fail), report_path,
                         self.dest if ok else None, message)
        except Exception as exc:
            discard_ok = self._discard()
            lines.append("")
            lines.append(traceback.format_exc())
            discard_warning = ""
            if not discard_ok:
                discard_warning = self._discard_warning()
                lines.append(discard_warning)

            report_path, report_err = self._write_report("\n".join(lines), False)

            if discard_warning:
                message = discard_warning
            elif report_err:
                message = f"the report could not be saved: {report_err}"
            else:
                message = _friendly(exc)

            res = Result(False, 0, 0, 0, report_path, None, message)
        emit({"kind": "done", "result": res})
        return res

    def _discard(self):
        """A failed run must leave nothing printable behind.

        Returns True if the destination is gone (including if it was never
        there), False if removal failed and a printable file may still exist.
        """
        try:
            self.dest.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _discard_warning(self):
        return f"could not delete {self.dest} — delete it yourself, do not print it"

    def _write_report(self, text, ok):
        """Never let a logging failure take down the run.

        Returns (path, None) on success or (None, reason) on failure.
        """
        try:
            return logstore.write_report(text, self.src.name, ok), None
        except OSError as exc:
            return None, str(exc)
