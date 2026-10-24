import branding
from test_cli_brand import run_cli

def _o(tmp_path): return ["-o", str(tmp_path / "o.pdf")]

def test_cli_defaults(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path))
    assert seen["build"]["prices"] is True and seen["build"]["pick_list"] is False
    assert seen["build"]["footer"] is None and seen["verify"] == seen["build"]

def test_cli_flags(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path), "--no-prices", "--pick-list")
    assert (seen["build"]["prices"], seen["build"]["pick_list"]) == (False, True)
    assert seen["verify"] == seen["build"]

def test_no_condense_flag(monkeypatch, tmp_path):
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path))
    assert seen["build"]["condense"] is True
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path), "--no-condense")
    assert seen["build"]["condense"] is False and seen["verify"]["condense"] is False
    seen = run_cli(monkeypatch, "verify", "a.pdf", "b.pdf", "--no-condense")
    assert seen["verify"]["condense"] is False

def test_cli_uses_the_detected_platform(monkeypatch, tmp_path, capsys):
    import platforms, tiktok
    seen = {}
    monkeypatch.setattr(tiktok, "build", lambda s, o, **kw: (seen.setdefault("tt", kw), open(o, "w").write("pdf"), (1, 1, 1))[2])
    class A:
        fail = []; checks = 1
        def report(self, t): return True
    monkeypatch.setattr(tiktok, "verify", lambda s, o, **kw: A())
    run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path))     # stubs detect as whatnot
    monkeypatch.setattr(platforms, "detect", lambda src: "tiktok")
    import sys, whatnot_slips as ws
    monkeypatch.setattr(sys, "argv", ["whatnot_slips.py", "build", "in.pdf", *_o(tmp_path)])
    assert ws.main() == 0
    assert "tt" in seen and "detected: TikTok Shop" in capsys.readouterr().out

def test_verify_subcommand_takes_the_flags(monkeypatch):
    seen = run_cli(monkeypatch, "verify", "a.pdf", "b.pdf", "--no-prices", "--pick-list")
    assert (seen["verify"]["prices"], seen["verify"]["pick_list"]) == (False, True)

def test_cli_reads_the_saved_footer_and_no_brand_drops_it(monkeypatch, tmp_path):
    branding.save(branding.Brand(footer_enabled=True, footer="Thanks!"))
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path))
    assert seen["build"]["footer"] == "Thanks!" and seen["verify"]["footer"] == "Thanks!"
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path), "--no-brand")
    assert seen["build"]["footer"] is None and seen["verify"]["footer"] is None
