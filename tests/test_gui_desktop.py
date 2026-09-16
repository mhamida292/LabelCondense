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
    monkeypatch.setattr(sys, "executable", "/opt/label-condense")
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
    monkeypatch.setattr(sys, "executable", "/opt/label-condense")
    monkeypatch.setattr(platform_bits, "install_desktop_entry",
                        lambda exe: (_ for _ in ()).throw(OSError("Read-only filesystem")))
    shown_error = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda *a, **k: shown_error.append((a, k)))
    app.maybe_offer_desktop_entry()  # Should not raise
    assert len(shown_error) == 1

def test_app_init_never_triggers_offer(monkeypatch):
    import packing_gui
    asked = []
    monkeypatch.setattr(packing_gui.messagebox, "askyesno",
                        lambda *a, **k: asked.append(1) or True)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    app = packing_gui.App(root)
    root.destroy()
    # App.__init__ should never trigger the offer dialog
    assert asked == []

def test_declining_on_unwritable_path_does_not_crash(app, monkeypatch):
    import packing_gui, platform_bits
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(platform_bits, "remember_desktop_choice",
                        lambda yes: (_ for _ in ()).throw(OSError("Read-only")))
    # Should not raise even though remember_desktop_choice fails
    app.maybe_offer_desktop_entry()

def test_failed_install_is_remembered(app, monkeypatch, tmp_path):
    import packing_gui, platform_bits, sys
    monkeypatch.setattr(platform_bits, "should_offer_desktop_entry", lambda: True)
    monkeypatch.setattr(packing_gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(sys, "executable", "/opt/label-condense")
    monkeypatch.setattr(platform_bits, "install_desktop_entry",
                        lambda exe: (_ for _ in ()).throw(OSError("Read-only")))
    shown_error = []
    monkeypatch.setattr(packing_gui.messagebox, "showerror",
                        lambda *a, **k: shown_error.append((a, k)))
    # First call: install fails, error shown, but choice is remembered
    app.maybe_offer_desktop_entry()
    assert len(shown_error) == 1
    # Check the error message (second positional arg) contains "will not ask again"
    error_message = shown_error[0][0][1]  # a[1] = message text
    assert "will not ask again" in error_message.lower()
    # Verify the choice was remembered
    monkeypatch.undo()
    assert platform_bits.should_offer_desktop_entry() is False
