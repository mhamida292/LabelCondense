import pytest

tk = pytest.importorskip("tkinter")
import branding


@pytest.fixture
def app(monkeypatch):
    import packing_gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = packing_gui.App(root)
    yield a
    root.destroy()


def _two_profiles():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"), "")
    pid = branding.create_profile("Knife Night")
    branding.save(branding.Brand(enabled=True, shop_name="Knives",
                                 footer_enabled=True, footer="See you Friday"), pid)
    return pid


def test_both_lists_show_every_profile():
    import packing_gui
    _two_profiles()
    root = tk.Tk(); root.withdraw()
    try:
        a = packing_gui.App(root)
        for box in (a.run_profile, a.profile_pick):
            assert list(box.cget("values")) == ["Default", "Knife Night"]
            assert box.get() == "Default"
        assert a.delete_btn.instate(["disabled"])          # Default can't be deleted
    finally:
        root.destroy()


def test_picking_on_the_run_tab_switches_the_form_and_is_remembered(app):
    pid = _two_profiles()
    app.refresh_profiles()
    app.run_profile.current(1)
    app._picked_profile(app.run_profile)
    assert branding.current_profile() == pid
    assert app.shop_name.get() == "Knives" and app.footer_on.get() is True
    assert app.footer_box.get("1.0", "end-1c") == "See you Friday"
    assert app.profile_pick.get() == "Knife Night" and app.brand_status.get() == ""
    assert app.delete_btn.instate(["!disabled"])


def test_unsaved_edits_ask_before_switching(app, monkeypatch):
    import packing_gui
    pid = _two_profiles()
    app.refresh_profiles()
    app.shop_name.set("Squish Co Live")                     # an unsaved edit
    monkeypatch.setattr(packing_gui.messagebox, "askyesnocancel", lambda *a: None)
    assert app.switch_profile(pid) is False                  # cancel: stay put
    assert branding.current_profile() == "" and app.run_profile.get() == "Default"
    monkeypatch.setattr(packing_gui.messagebox, "askyesnocancel", lambda *a: True)
    assert app.switch_profile(pid) is True                   # yes: saved, then moved
    assert branding.load("").shop_name == "Squish Co Live"
    assert app.shop_name.get() == "Knives"


def test_new_rename_delete(app, monkeypatch):
    import packing_gui
    names = iter(["Blades Plus", "Blades Plus Live"])
    monkeypatch.setattr(packing_gui.simpledialog, "askstring", lambda *a, **k: next(names))
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a: True)
    app.new_profile()
    pid = branding.current_profile()
    assert pid and app.run_profile.get() == "Blades Plus"
    app.rename_profile()
    assert app.profile_pick.get() == "Blades Plus Live"
    app.delete_profile()
    assert branding.current_profile() == "" and list(app.run_profile.cget("values")) == ["Default"]


def test_a_run_uses_the_picked_profile(app, monkeypatch, tmp_path):
    import packing_gui
    pid = _two_profiles()
    seen = {}
    class FakeJob:
        def __init__(self, src, dest, **kw): seen.update(kw)
        def run(self, emit): pass
    monkeypatch.setattr(packing_gui.jobmod, "Job", FakeJob)
    monkeypatch.setattr(app, "ask_destination", lambda: tmp_path / "o.pdf")
    app.switch_profile(pid)
    app.src = tmp_path / "in.pdf"
    app.start()
    assert seen["brand"].shop_name == "Knives" and seen["footer"] == "See you Friday"
    assert seen["profile"] == "Knife Night"
    app.root.after_cancel(app._after_id)


def test_logo_prompt_uses_the_shop_name_and_the_box_size():
    p = branding.logo_prompt("Blades Plus")
    assert '"Blades Plus"' in p and "1350 x 450" in p and "black" in p
    assert "[your shop name]" in branding.logo_prompt("")
    w, h = branding.PROMPT_PX
    assert w * branding.LOGO_PX[1] == h * branding.LOGO_PX[0]   # same shape as the box


def test_logo_prompt_window_and_copy(app):
    app.shop_name.set("Knife Night")
    app.show_logo_prompt()
    assert "Knife Night" in app.prompt_win.winfo_children()[0].winfo_children()[1].get("1.0", "end")
    app.copy_logo_prompt()
    assert app.root.clipboard_get() == branding.logo_prompt("Knife Night")
    app.prompt_win.destroy()
