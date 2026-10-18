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

def test_verify_subcommand_takes_the_flags(monkeypatch):
    seen = run_cli(monkeypatch, "verify", "a.pdf", "b.pdf", "--no-prices", "--pick-list")
    assert (seen["verify"]["prices"], seen["verify"]["pick_list"]) == (False, True)

def test_cli_reads_the_saved_footer_and_no_brand_drops_it(monkeypatch, tmp_path):
    branding.save(branding.Brand(footer_enabled=True, footer="Thanks!"))
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path))
    assert seen["build"]["footer"] == "Thanks!" and seen["verify"]["footer"] == "Thanks!"
    seen = run_cli(monkeypatch, "build", "in.pdf", *_o(tmp_path), "--no-brand")
    assert seen["build"]["footer"] is None and seen["verify"]["footer"] is None
