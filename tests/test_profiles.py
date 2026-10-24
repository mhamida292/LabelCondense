import json

import pytest
from PIL import Image

import branding
import job as J
from test_cli_brand import run_cli


def sdir():
    return branding.settings_dir()


# ------------------------------------------------------------------ storage
def test_existing_branding_is_the_default_profile():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    assert branding.profiles() == [("", "Default")]
    assert branding.current_profile() == ""
    assert branding.load().shop_name == "Squish Co"
    # still the same file it always was
    assert json.loads((sdir() / "settings.json").read_text())["shop_name"] == "Squish Co"


def test_profiles_keep_their_own_branding_and_logo():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    pid = branding.create_profile("Blades Plus")
    assert branding.load(pid).shop_name == ""                 # starts blank...
    pid = branding.create_profile("Knife Night", copy_from="")  # ...or as a copy
    assert branding.load(pid).shop_name == "Squish Co"
    logo = Image.new("1", (40, 20), 0)
    branding.save(branding.Brand(enabled=True, shop_name="Knives", logo=logo,
                                 footer_enabled=True, footer="See you Friday"), pid)
    assert branding.load("").shop_name == "Squish Co" and branding.load("").logo is None
    b = branding.load(pid)
    assert (b.shop_name, b.footer, b.profile) == ("Knives", "See you Friday", "Knife Night")
    assert b.logo is not None


def test_a_new_profile_without_a_source_starts_blank():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"))
    pid = branding.create_profile("Fresh")
    assert branding.load(pid).shop_name == ""


def test_profiles_list_default_first_then_by_name():
    branding.create_profile("zebra"); branding.create_profile("Apple")
    assert [n for _, n in branding.profiles()] == ["Default", "Apple", "zebra"]


def test_the_current_profile_drives_load_active_and_save():
    a = branding.create_profile("A")
    branding.save(branding.Brand(enabled=True, shop_name="Alpha"), a)
    branding.set_current_profile(a)
    assert branding.current_profile() == a
    assert branding.active().shop_name == "Alpha"
    branding.save(branding.Brand(enabled=True, shop_name="Alpha 2"))
    assert branding.load(a).shop_name == "Alpha 2" and branding.load("").shop_name == ""


@pytest.mark.parametrize("name,err", [("", "Give the profile a name"),
                                      ("x" * 41, "up to 40"),
                                      ("default", "already a profile")])
def test_bad_names_are_refused(name, err):
    with pytest.raises(ValueError, match=err):
        branding.create_profile(name)


def test_rename_keeps_the_settings_and_the_selection():
    pid = branding.create_profile("Blades")
    branding.save(branding.Brand(enabled=True, shop_name="Blades Plus"), pid)
    branding.set_current_profile(pid)
    branding.rename_profile(pid, "Blades Plus Live")
    assert branding.profile_name(pid) == "Blades Plus Live"
    assert branding.load().shop_name == "Blades Plus"
    branding.rename_profile("", "Main shop")          # Default can be named too
    assert branding.profiles()[0] == ("", "Main shop")
    assert branding.load("").profile == "Main shop"


def test_delete_falls_back_to_default_and_default_stays():
    pid = branding.create_profile("Gone")
    branding.save(branding.Brand(logo=Image.new("1", (8, 8), 0)), pid)
    branding.set_current_profile(pid)
    branding.delete_profile(pid)
    assert branding.current_profile() == "" and branding.profiles() == [("", "Default")]
    assert list((sdir() / "profiles").iterdir()) == []
    with pytest.raises(ValueError):
        branding.delete_profile("")


def test_a_remembered_profile_that_is_gone_means_default():
    branding.set_current_profile("p9")
    assert branding.current_profile() == ""


# --------------------------------------------------------------------- CLI
def test_cli_profile_flag_picks_that_branding(monkeypatch, tmp_path, capsys):
    pid = branding.create_profile("Knife Night")
    branding.save(branding.Brand(enabled=True, shop_name="Knives"), pid)
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co"), "")
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"),
                   "--profile", "knife night")
    assert seen["build"]["brand"].shop_name == "Knives"
    assert "branding profile: Knife Night" in capsys.readouterr().out
    seen = run_cli(monkeypatch, "build", "in.pdf", "-o", str(tmp_path / "o.pdf"))
    assert seen["build"]["brand"].shop_name == "Squish Co"   # current is still Default


def test_cli_unknown_profile_is_an_error(monkeypatch, tmp_path, capsys):
    import sys, platforms, whatnot_slips as ws
    monkeypatch.setattr(platforms, "detect", lambda src: "whatnot")
    monkeypatch.setattr(sys, "argv", ["whatnot_slips.py", "build", "in.pdf",
                                      "-o", str(tmp_path / "o.pdf"), "--profile", "Nope"])
    assert ws.main() == 1
    assert "no branding profile called 'Nope'" in capsys.readouterr().out


# --------------------------------------------------------------------- job
def test_job_logs_the_profile(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setenv("PACKING_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(J.platforms, "detect", lambda s: "whatnot")
    monkeypatch.setattr(J.ws, "build", lambda s, o, **kw: (pathlib.Path(o).write_text("x"), (1, 1, 1))[1])
    class A:
        checks = 1; fail = []
        def text(self, t): return t
    monkeypatch.setattr(J.ws, "verify", lambda *a, **kw: A())
    monkeypatch.setattr(J.ws, "pdf_pages", lambda p: ["a"])
    src = tmp_path / "in.pdf"; src.write_text("x")
    lines = []
    J.Job(src, tmp_path / "o.pdf", profile="Knife Night").run(
        lambda e: lines.append(e["line"]) if e["kind"] == "log" else None)
    assert "branding profile: Knife Night" in lines
