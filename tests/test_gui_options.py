import pytest

tk = pytest.importorskip("tkinter")
import branding
import recent

def _make():
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    return root, packing_gui.App(root)

@pytest.fixture
def app():
    root, a = _make()
    yield a
    root.destroy()

@pytest.fixture
def errors(monkeypatch):
    import packing_gui
    shown = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda title, msg: shown.append(msg))
    return shown

def test_footer_counter_and_cap(app):
    app.footer_box.insert("1.0", "x" * 150); app.root.update()
    assert len(app.footer_box.get("1.0", "end-1c")) == 120
    assert app.footer_count.get() == "120 / 120"

def test_message_counter_and_cap(app):
    app.message_box.delete("1.0", "end")
    app.message_box.insert("1.0", "x" * 90); app.root.update()
    assert len(app.message_box.get("1.0", "end-1c")) == 60
    assert app.message_count.get() == "60 / 60"

def test_message_counter_correct_after_construction(app):
    assert app.message_count.get() == f"{len(branding.DEFAULT_MESSAGE)} / 60"

def test_footer_counter_correct_after_construction():
    branding.save(branding.Brand(footer_enabled=True, footer="Thanks!"))
    root, a = _make()
    try:
        assert a.footer_count.get() == "7 / 120"
        assert a.footer_on.get() is True
    finally:
        root.destroy()

def test_footer_edit_marks_unsaved(app):
    app.brand_status.set("Saved")
    app.footer_box.insert("1.0", "hi"); app.root.update()
    assert app.brand_status.get() == "Not saved yet"
    assert app.footer_count.get() == "2 / 120"

def test_footer_saves_with_its_own_switch(app, errors):
    app.footer_on.set(True)
    app.footer_box.insert("1.0", "Thanks for shopping!")
    assert app.save_branding() is True and not errors
    assert branding.active_footer() == "Thanks for shopping!"
    assert app.form_brand().footer_enabled is True

def test_footer_locks_during_run(app):
    app._lock_branding(True)
    assert str(app.footer_box.cget("state")) == "disabled"
    app._lock_branding(False)
    assert str(app.footer_box.cget("state")) == "normal"

def test_run_switches_default_and_persist(app):
    assert app.show_prices.get() is True and app.pick_list.get() is False
    assert app.condense.get() is True
    app.show_prices.set(False); app.pick_list.set(True); app.condense.set(False)
    root, b = _make()
    try:
        assert b.show_prices.get() is False and b.pick_list.get() is True
        assert b.condense.get() is False
    finally:
        root.destroy()

def test_start_passes_switches_to_job(app, monkeypatch, tmp_path):
    import packing_gui
    seen = {}
    class FakeJob:
        def __init__(self, src, dest, **kw):
            seen.update(kw)
        def run(self, emit): pass
    monkeypatch.setattr(packing_gui.jobmod, "Job", FakeJob)
    monkeypatch.setattr(app, "ask_destination", lambda: tmp_path / "o.pdf")
    branding.save(branding.Brand(footer_enabled=True, footer="Bye"))
    app.src = tmp_path / "in.pdf"
    app.show_prices.set(False); app.pick_list.set(True); app.condense.set(False)
    app.start()
    assert seen["prices"] is False and seen["pick_list"] is True
    assert seen["condense"] is False
    assert seen["footer"] == "Bye"
    app.root.after_cancel(app._after_id)

def test_preview_passes_footer_prices_and_brand(app, monkeypatch):
    import packing_gui
    calls = []
    def fake(brand, png, footer=None, prices=True):
        calls.append((brand, footer, prices))
        from PIL import Image
        Image.new("RGB", (4, 4)).save(png)
    monkeypatch.setattr(packing_gui.ws, "preview_png", fake)
    app.footer_on.set(True); app.footer_box.insert("1.0", "Hey")
    app.show_prices.set(False)
    app.preview_slip()
    brand, footer, prices = calls[0]
    assert brand is None and footer == "Hey" and prices is False

def test_prefs_round_trip_and_survive_junk():
    assert recent.get_pref("show_prices", True) is True
    recent.set_pref("show_prices", False)
    assert recent.get_pref("show_prices", True) is False
    recent.set_pref("show_prices", "yes")
    assert recent.get_pref("show_prices", True) is True   # wrong type
    recent._prefs_path().write_text("{junk", encoding="utf-8")
    assert recent.get_pref("pick_list", False) is False
    recent.set_pref("pick_list", True)
    assert recent.get_pref("pick_list", False) is True
