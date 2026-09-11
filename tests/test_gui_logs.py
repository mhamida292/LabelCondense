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
