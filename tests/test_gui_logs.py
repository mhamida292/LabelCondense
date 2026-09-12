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
    # pump() always appends to log_lines and the pane together; mirror that here.
    app.log_lines.append("built out.pdf: 122 shipments")
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

def test_opening_logs_tab_loads_newest_report_into_pane(app):
    import logstore
    logstore.write_report("the newest body", "new.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    app.tab("logs")
    assert "the newest body" in app.log_text()

def test_pane_stays_in_sync_when_a_new_run_finishes(app):
    import logstore
    logstore.write_report("older body", "old.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.tab("logs")
    app.select_report(0)          # the only report, loaded automatically anyway
    assert "older body" in app.log_text()
    logstore.write_report("brand new body", "new.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    app.refresh_logs()            # what finish() calls
    assert app.picker.current() == 0
    assert "brand new body" in app.log_text()
    assert "older body" not in app.log_text()

def test_select_report_index_offset_while_working(app):
    import logstore
    logstore.write_report("REPORT-NEWER", "b.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    logstore.write_report("REPORT-OLDER", "a.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.show("working")
    app.log_lines = ["live tail line"]
    app.tab("logs")
    # dropdown is ["This run", REPORT-NEWER's label, REPORT-OLDER's label]
    app.select_report(1)
    assert "REPORT-NEWER" in app.log_text()
    assert "REPORT-OLDER" not in app.log_text()
    app.select_report(2)
    assert "REPORT-OLDER" in app.log_text()
    assert "REPORT-NEWER" not in app.log_text()
    # and index 0 still shows the live tail, not wiped by the above
    app.select_report(0)
    assert "live tail line" in app.log_text()

def test_select_report_index_offset_when_not_working(app):
    import logstore
    logstore.write_report("REPORT-NEWER", "b.pdf", True, dt.datetime(2026, 9, 11, 8, 0))
    logstore.write_report("REPORT-OLDER", "a.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.tab("logs")
    # dropdown is [REPORT-NEWER's label, REPORT-OLDER's label] — no "This run" offset
    app.select_report(0)
    assert "REPORT-NEWER" in app.log_text()
    assert "REPORT-OLDER" not in app.log_text()
    app.select_report(1)
    assert "REPORT-OLDER" in app.log_text()
    assert "REPORT-NEWER" not in app.log_text()

def test_select_report_ignores_negative_index(app):
    import logstore
    logstore.write_report("some body", "x.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    app.tab("logs")
    app._set_log("sentinel text")
    app.select_report(-1)
    assert app.log_text() == "sentinel text"

def test_save_report_shows_error_instead_of_raising(app, tmp_path, monkeypatch):
    import packing_gui, logstore
    logstore.write_report("body", "x.pdf", True, dt.datetime(2026, 9, 1, 8, 0))
    target = tmp_path / "sent.txt"
    monkeypatch.setattr(packing_gui.filedialog, "asksaveasfilename", lambda **kw: str(target))
    monkeypatch.setattr(packing_gui.pathlib.Path, "write_text",
                         lambda self, *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    calls = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                         lambda title, msg: calls.append((title, msg)))
    app.tab("logs"); app.select_report(0)
    app.save_report()             # must not raise
    assert calls
    assert str(target) in calls[0][1]

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
