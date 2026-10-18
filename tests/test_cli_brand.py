import sys
import branding
import whatnot_slips as ws

def run_cli(monkeypatch, *argv):
    seen = {}
    def fake_build(s, o, quiet=False, progress=None, **kw):
        seen["build"] = kw; open(o, "w").write("pdf"); return (1, 1, 1)
    class A:
        fail = []; checks = 1
        def report(self, t): return True
    def fake_verify(s, o, deep=False, progress=None, **kw):
        seen["verify"] = kw; return A()
    monkeypatch.setattr(ws, "build", fake_build)
    monkeypatch.setattr(ws, "verify", fake_verify)
    monkeypatch.setattr(sys, "argv", ["whatnot_slips.py", *argv])
    assert ws.main() == 0
    return seen

def test_cli_uses_saved_branding_by_default(monkeypatch, tmp_path):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen["build"]["brand"].shop_name == "Squish Co"
    assert seen["verify"]["brand"] is seen["build"]["brand"]

def test_no_brand_flag_turns_it_off(monkeypatch, tmp_path):
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"), "--no-brand")
    assert seen["build"]["brand"] is None and seen["verify"]["brand"] is None

def test_branding_switched_off_means_none(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen["build"]["brand"] is None and seen["verify"]["brand"] is None

def test_verify_subcommand_takes_the_flag_too(monkeypatch):
    branding.save(branding.Brand(enabled=True))
    seen = run_cli(monkeypatch, "verify", "a.pdf", "b.pdf", "--no-brand")
    assert "build" not in seen and seen["verify"]["brand"] is None

def test_a_dropped_footer_is_logged_even_with_header_branding_off(monkeypatch, tmp_path, capsys):
    import json
    path = branding._settings_path(); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"footer_enabled": True, "footer": "x " * 200}))
    run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert capsys.readouterr().out.count("branding: footer too long") == 1
