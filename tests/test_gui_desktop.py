import pytest
tk = pytest.importorskip("tkinter")

@pytest.fixture
def app(tmp_path, monkeypatch):
    import packing_gui
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    yield packing_gui.App(root)
    root.destroy()

def test_accepting_installs_entry(app, monkeypatch, tmp_path):
    import packing_gui, platform_bits, sys
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(sys, "executable", "/opt/packing-slips")
    app.maybe_offer_desktop_entry()
    assert platform_bits.desktop_entry_path().exists()

def test_declining_is_remembered(app, monkeypatch):
    import packing_gui, platform_bits
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: False)
    app.maybe_offer_desktop_entry()
    assert not platform_bits.desktop_entry_path().exists()
    monkeypatch.undo()
    assert platform_bits.should_offer_desktop_entry() is False

def test_not_offered_when_helper_says_no(app, monkeypatch):
    import packing_gui, platform_bits
    asked = []
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: False)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno",
                        lambda *a, **k: asked.append(1) or True)
    app.maybe_offer_desktop_entry()
    assert asked == []

def test_oserror_on_install_does_not_propagate(app, monkeypatch):
    import packing_gui, platform_bits, sys
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(sys, "executable", "/opt/packing-slips")
    monkeypatch.setattr(platform_bits, "install_desktop_entry",
                        lambda exe: (_ for _ in ()).throw(OSError("Read-only filesystem")))
    shown_error = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda *a, **k: shown_error.append((a, k)))
    app.maybe_offer_desktop_entry()  # Should not raise
    assert len(shown_error) == 1
