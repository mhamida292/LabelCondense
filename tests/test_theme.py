import pytest

tk = pytest.importorskip("tkinter")
import platform_bits as pb
import theme

@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    r.withdraw()
    yield r
    r.destroy()

@pytest.mark.parametrize("dark,mode", [(True, "dark"), (False, "light")])
def test_theme_loads_in_the_requested_mode(root, dark, mode):
    theme.apply(root, dark=dark)
    assert theme.mode(root) == mode
    assert theme.palette(root) is theme.PALETTE[mode]

def test_window_gets_the_app_icon(root):
    theme.apply(root, dark=False)
    assert root._icon.width() == 256

def test_the_vendored_theme_is_teal_not_sun_valley_blue():
    for mode in ("light", "dark"):
        tcl = theme.asset(f"sv/theme/{mode}.tcl").read_text()
        assert "#005fb8" not in tcl and "#57c8ff" not in tcl
    assert theme.asset("sv/LICENSE").is_file()

def test_themed_app_marks_the_current_tab(root):
    import packing_gui
    theme.apply(root, dark=True)
    app = packing_gui.App(root)
    assert app.colors is theme.PALETTE["dark"]
    assert app.run_btn.instate(["selected"])
    app.tab("branding")
    assert app.brand_btn.instate(["selected"]) and not app.run_btn.instate(["selected"])
    assert app.message_box.cget("background") == theme.PALETTE["dark"]["field"]

def test_a_missing_theme_leaves_the_default_look(root, monkeypatch, tmp_path):
    monkeypatch.setattr(theme, "asset", lambda name: tmp_path / name)
    theme.apply(root, dark=True)              # must not raise
    assert theme.mode(root) == "light"

# ------------------------------------------------------------ prefers_dark
@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(pb, "_mac", lambda: False)

def fake_probe(monkeypatch, answers):
    monkeypatch.setattr(pb, "_quiet", lambda argv: answers.get(argv[0], ""))

def test_portal_dark_and_light(linux, monkeypatch):
    fake_probe(monkeypatch, {"gdbus": "(<<uint32 1>>,)\n"}); assert pb.prefers_dark()
    fake_probe(monkeypatch, {"gdbus": "(<<uint32 0>>,)\n"}); assert not pb.prefers_dark()
    # "no preference" (2) is light, even when GNOME's own key says otherwise
    fake_probe(monkeypatch, {"gdbus": "(<<uint32 2>>,)\n", "gsettings": "'prefer-dark'"})
    assert not pb.prefers_dark()

def test_without_a_portal_gnome_setting_decides(linux, monkeypatch):
    fake_probe(monkeypatch, {"gsettings": "'prefer-dark'\n"}); assert pb.prefers_dark()
    fake_probe(monkeypatch, {}); assert not pb.prefers_dark()

def test_mac_reads_apple_interface_style(monkeypatch):
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(pb, "_mac", lambda: True)
    fake_probe(monkeypatch, {"defaults": "Dark\n"}); assert pb.prefers_dark()
    fake_probe(monkeypatch, {}); assert not pb.prefers_dark()

def test_quiet_probe_survives_a_missing_tool():
    assert pb._quiet(["no-such-tool-label-condense"]) == ""
