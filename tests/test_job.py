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

@pytest.fixture(autouse=True)
def detected_as_whatnot(monkeypatch):
    """The fake inputs here aren't PDFs; the stubs stand in for Whatnot's."""
    monkeypatch.setattr(J.platforms, "detect", lambda src: "whatnot")

def test_success_writes_output_and_report(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    def fake_build(s, o, quiet=False, progress=None, brand=None, **kw):
        pathlib.Path(o).write_text("pdf")
        if progress: progress(1, 1, "building slips")
        return (122, 123, 122)
    monkeypatch.setattr(J.ws, "build", fake_build)
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None, brand=None, **kw: FakeAudit(0))
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
        lambda s, o, quiet=False, progress=None, brand=None, **kw: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None, brand=None, **kw: FakeAudit(14))
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
    assert "Whatnot or TikTok Shop export" in res.message
    assert "IndexError" not in res.message

def test_discard_failure_is_reported_not_swallowed(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    monkeypatch.setattr(J.ws, "build",
        lambda s, o, quiet=False, progress=None, brand=None, **kw: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None, brand=None, **kw: FakeAudit(14))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])

    def raise_unlink(self, missing_ok=False):
        raise PermissionError("locked")
    monkeypatch.setattr(pathlib.Path, "unlink", raise_unlink)

    res = J.Job(src, dest).run(lambda e: None)
    assert res.ok is False
    assert str(dest) in res.message
    assert "do not print" in res.message
    assert str(dest) in res.report_path.read_text()

def test_report_write_failure_still_returns_a_result(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    def boom(*a, **k): raise RuntimeError("kaboom")
    monkeypatch.setattr(J.ws, "build", boom)
    def bad_write_report(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(J.logstore, "write_report", bad_write_report)

    res = J.Job(src, dest).run(lambda e: None)
    assert res.ok is False
    assert res.dest is None
    assert res.report_path is None
    assert "could not be saved" in res.message

def test_friendly_permission_error_is_actionable():
    msg = J._friendly(PermissionError("nope"))
    assert "can't be written to" in msg

def test_source_is_never_modified(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("original")
    dest = tmp_path / "out.pdf"
    monkeypatch.setattr(J.ws, "build",
        lambda s, o, quiet=False, progress=None, brand=None, **kw: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda s, o, deep=False, progress=None, brand=None, **kw: FakeAudit(0))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    J.Job(src, dest).run(lambda e: None)
    assert src.read_text() == "original" and src.exists()

def test_brand_reaches_build_and_verify_and_notes_reach_the_log(tmp_path, monkeypatch):
    import branding
    src = tmp_path / "in.pdf"; src.write_text("x")
    dest = tmp_path / "out.pdf"
    seen = {}
    def fake_build(s, o, quiet=False, progress=None, brand=None, **kw):
        seen["build"] = brand; pathlib.Path(o).write_text("pdf"); return (1, 1, 1)
    def fake_verify(s, o, deep=False, progress=None, brand=None, **kw):
        seen["verify"] = brand; return FakeAudit(0)
    monkeypatch.setattr(J.ws, "build", fake_build)
    monkeypatch.setattr(J.ws, "verify", fake_verify)
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    b = branding.Brand(enabled=True, notes=["logo unreadable (x); showing the shop name instead"])
    lines = []
    res = J.Job(src, dest, brand=b).run(
        lambda e: lines.append(e["line"]) if e["kind"] == "log" else None)
    assert res.ok and seen == {"build": b, "verify": b}
    assert any("logo unreadable" in l for l in lines)

def test_job_passes_footer_prices_and_pick_list(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    seen = {}
    def fake_build(s, o, quiet=False, progress=None, **kw):
        seen["build"] = kw; pathlib.Path(o).write_text("pdf"); return (1, 1, 1)
    def fake_verify(s, o, deep=False, progress=None, **kw):
        seen["verify"] = kw; return FakeAudit(0)
    monkeypatch.setattr(J.ws, "build", fake_build)
    monkeypatch.setattr(J.ws, "verify", fake_verify)
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    J.Job(src, tmp_path / "out.pdf", footer="Hi", prices=False, pick_list=True,
          condense=False).run(lambda e: None)
    want = {"brand": None, "footer": "Hi", "prices": False, "pick_list": True,
            "condense": False}
    assert seen["build"] == want and seen["verify"] == want


def test_explicit_notes_reach_the_log_even_with_branding_off(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"; src.write_text("x")
    monkeypatch.setattr(J.ws, "build", lambda s, o, **kw: (pathlib.Path(o).write_text("pdf"), (1, 1, 1))[1])
    monkeypatch.setattr(J.ws, "verify", lambda *a, **kw: FakeAudit(0))
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    lines = []
    J.Job(src, tmp_path / "out.pdf", notes=["footer too long for 2 lines; not printed"]).run(
        lambda e: lines.append(e["line"]) if e["kind"] == "log" else None)
    assert [l for l in lines if "footer too long" in l] == ["branding: footer too long for 2 lines; not printed"]
