import pytest
from PIL import Image

tk = pytest.importorskip("tkinter")
import branding

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

@pytest.fixture
def errors(monkeypatch):
    import packing_gui
    shown = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda title, msg: shown.append(msg))
    return shown

def test_branding_tab_exists(app):
    app.tab("branding")
    assert app.current_tab == "branding"

def test_form_starts_from_saved_settings(monkeypatch):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co", message="Hi!"))
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        a = packing_gui.App(root)
        b = a.form_brand()
        assert (b.enabled, b.shop_name, b.message) == (True, "Squish Co", "Hi!")
    finally:
        root.destroy()

def test_save_writes_settings(app, errors):
    app.brand_on.set(True); app.shop_name.set("Squish Co")
    assert app.save_branding() is True and errors == []
    assert branding.load().shop_name == "Squish Co"

def test_save_refuses_an_overlong_message(app, errors):
    app.message_box.delete("1.0", "end")
    app.message_box.insert("1.0", "word " * 80)
    assert app.save_branding() is False
    assert "2 lines" in errors[0]
    assert branding.load().message == branding.DEFAULT_MESSAGE

def test_choosing_a_logo_does_not_change_what_prints_until_save(app, errors, tmp_path):
    p = tmp_path / "l.png"; Image.new("L", (300, 100), 0).save(p)
    app.choose_logo(str(p))
    assert errors == [] and app.form_brand().logo is not None
    assert branding.load().logo is None
    app.save_branding()
    assert branding.load().logo is not None

def test_a_bad_logo_shows_an_error_and_keeps_the_old_one(app, errors, tmp_path):
    p = tmp_path / "x.png"; p.write_text("nope")
    app.choose_logo(str(p))
    assert len(errors) == 1 and app.form_brand().logo is None

def test_remove_logo_clears_the_form(app, tmp_path):
    p = tmp_path / "l.png"; Image.new("L", (300, 100), 0).save(p)
    app.choose_logo(str(p)); app.remove_logo()
    assert app.form_brand().logo is None

def test_branding_is_locked_while_a_run_is_working(app):
    app.show("working")
    assert app.brand_save_btn.instate(["disabled"])
    assert str(app.message_box.cget("state")) == "disabled"
    app.show("idle")
    assert not app.brand_save_btn.instate(["disabled"])

def test_start_hands_the_saved_brand_to_the_job(app, monkeypatch, tmp_path):
    import packing_gui
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = {}
    monkeypatch.setattr(app, "ask_destination", lambda: tmp_path / "o.pdf")
    monkeypatch.setattr(packing_gui.jobmod.Job, "run",
                        lambda self, emit: seen.setdefault("brand", self.brand))
    app.src = tmp_path / "in.pdf"
    app.start()
    app.root.after_cancel(app._after_id)
    import time; time.sleep(0.2)
    assert seen["brand"].shop_name == "Squish Co"
