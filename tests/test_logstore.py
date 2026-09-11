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

def test_list_reports_tolerates_unreadable_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    # Write a good report
    logstore.write_report("good", "ok.pdf", True, dt.datetime(2026, 9, 11, 10, 0))
    # Write non-UTF-8 bytes to a .log file
    (tmp_path / "logs" / "junk.log").write_bytes(b"\xff\xfe\x00binary")
    # list_reports() should return just the good one, not raise
    reports = logstore.list_reports()
    assert len(reports) == 1
    assert reports[0].source == "ok.pdf"
