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
    assert app.root.title() == "Label Condense"

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
