import datetime as dt, os, subprocess, sys
import pytest
import dialogs, platform_bits, recent

NOW = dt.datetime(2026, 10, 14, 12, 0)

def touch(path, when):
    path.write_bytes(b"%PDF"); t = when.timestamp(); os.utime(path, (t, t))
    return path

def test_newest_whatnot_export_in_downloads_is_offered(tmp_path):
    dl = recent.downloads()
    touch(dl / "Whatnot-Combined-Labels-Packing-Slips-aaa-1.pdf", NOW - dt.timedelta(hours=3))
    new = touch(dl / "Whatnot-Combined-Labels-Packing-Slips-bbb-1 (1).pdf", NOW - dt.timedelta(minutes=5))
    touch(dl / "invoice.pdf", NOW)                                   # not an export
    touch(dl / "2026-10-14-slips.pdf", NOW)                          # our own output
    assert recent.newest_export(NOW)[0] == new

def test_exports_older_than_a_week_are_not_offered(tmp_path):
    touch(recent.downloads() / "Whatnot-Combined-Labels-Packing-Slips-x-1.pdf", NOW - dt.timedelta(days=8))
    assert recent.newest_export(NOW) is None

def test_the_last_used_folder_is_searched_and_opened(tmp_path):
    shows = tmp_path / "shows"; shows.mkdir()
    f = touch(shows / "whatnot-labels.pdf", NOW - dt.timedelta(minutes=1))
    assert recent.export_dir() == recent.downloads()
    recent.remember_folder(f)
    assert recent.export_dir() == shows
    assert recent.newest_export(NOW)[0] == f

def test_a_vanished_remembered_folder_falls_back_to_downloads(tmp_path):
    recent.remember_folder(tmp_path / "gone" / "x.pdf")
    assert recent.export_dir() == recent.downloads()

def test_corrupt_prefs_are_ignored():
    recent._prefs_path().write_text("{nope")
    assert recent.export_dir() == recent.downloads()

@pytest.mark.parametrize("secs,text", [(5, "just now"), (300, "5 min ago"), (7200, "2 h ago"),
                                       (90000, "yesterday"), (3 * 86400, "3 days ago")])
def test_age(secs, text):
    assert recent.age(NOW - dt.timedelta(seconds=secs), NOW) == text

def test_short_keeps_both_ends():
    name = "Whatnot-Combined-Labels-Packing-Slips-60bad3e4-1 (1).pdf"
    s = recent.short(name)
    assert len(s) <= 44 and s.startswith("Whatnot-") and s.endswith("-1 (1).pdf")

# ----------------------------------------------------------------- dialogs
PDF = [("PDF files", "*.pdf")]

def test_kdialog_and_zenity_command_lines(tmp_path):
    assert dialogs._argv("kdialog", False, "T", tmp_path, PDF) == \
        ["kdialog", "--title", "T", "--getopenfilename", str(tmp_path), "PDF files (*.pdf)"]
    z = dialogs._argv("zenity", True, "T", tmp_path / "a.pdf", PDF)
    assert z[:2] == ["zenity", "--file-selection"] and "--save" in z
    assert f"--filename={tmp_path / 'a.pdf'}" in z and "--file-filter=PDF files | *.pdf" in z

def fake_native(monkeypatch, rc, out=""):
    monkeypatch.setattr(dialogs, "_native_tool", lambda: "kdialog")
    monkeypatch.setattr(dialogs, "_run", lambda root, argv:
                        subprocess.CompletedProcess(argv, rc, out, ""))

def test_native_pick_cancel_and_failure(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(dialogs.filedialog, "askopenfilename",
                        lambda **kw: called.append(kw) or "/from/tk.pdf")
    fake_native(monkeypatch, 0, "/home/u/x.pdf\n")
    assert dialogs.ask_open(None, "T", tmp_path, PDF) == "/home/u/x.pdf"
    fake_native(monkeypatch, 1)
    assert dialogs.ask_open(None, "T", tmp_path, PDF) == ""          # cancelled: no Tk dialog
    assert called == []
    fake_native(monkeypatch, 127)                                     # broken tool: Tk takes over
    assert dialogs.ask_open(None, "T", tmp_path, PDF) == "/from/tk.pdf"

def test_native_save_adds_the_extension(monkeypatch, tmp_path):
    fake_native(monkeypatch, 0, "/home/u/slips\n")
    assert dialogs.ask_save(None, "T", tmp_path, "a.pdf", PDF, ".pdf") == "/home/u/slips.pdf"

def test_a_second_picker_cannot_open_while_one_is_up(monkeypatch, tmp_path):
    monkeypatch.setattr(dialogs, "_busy", True)
    assert dialogs.ask_open(None, "T", tmp_path, PDF) == ""

# --------------------------------------------------------------- clean_env
def test_frozen_build_hands_tools_the_users_library_path(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/lib")
    assert platform_bits.clean_env()["LD_LIBRARY_PATH"] == "/opt/lib"
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in platform_bits.clean_env()

def test_unfrozen_env_is_untouched(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/x")
    assert platform_bits.clean_env()["LD_LIBRARY_PATH"] == "/x"

def test_remember_folder_keeps_other_prefs(tmp_path):
    recent.set_pref("pick_list", True)
    recent.remember_folder(tmp_path / "x.pdf")
    assert recent.get_pref("pick_list", False) is True
    assert recent.export_dir() == tmp_path
