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

def test_finish_from_logs_tab_switches_to_run_tab(app, tmp_path):
    """If a run finishes while the user is on the Logs tab, the verdict must
    still surface immediately rather than being hidden behind that tab."""
    import job
    app.tab("logs")
    r = job.Result(True, 304, 3743, 0, tmp_path / "r.log", tmp_path / "o.pdf", "")
    app.queue.put({"kind": "done", "result": r})
    app.pump()
    assert app.current_tab == "run"
    assert app.state == "done"

def test_failed_result_badge_survives_tab_switch(app, tmp_path):
    """tab('logs') clears the badge, so finish() must switch tabs before
    marking failure, not after, or the badge is wiped immediately."""
    import job
    app.tab("logs")
    r = job.Result(False, 0, 3743, 14, tmp_path / "r.log", None, "14 checks failed")
    app.queue.put({"kind": "done", "result": r})
    app.pump()
    assert app.state == "failed"
    assert app.badge_visible is True
