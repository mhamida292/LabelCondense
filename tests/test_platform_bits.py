import os, pathlib, sys
import platform_bits as pb

def test_open_for_print_uses_startfile_on_windows(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pb, "_windows", lambda: True)
    monkeypatch.setattr(os, "startfile", lambda p, verb=None: calls.append((p, verb)), raising=False)
    f = tmp_path / "a.pdf"; f.write_text("x")
    pb.open_for_print(f)
    assert calls == [(str(f), "print")]

def test_open_for_print_uses_xdg_on_linux(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(pb.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    f = tmp_path / "a.pdf"; f.write_text("x")
    pb.open_for_print(f)
    assert calls == [["xdg-open", str(f)]]

def test_reveal_opens_parent_directory(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(pb.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    pb.reveal(tmp_path)
    assert calls == [["xdg-open", str(tmp_path)]]

def test_desktop_entry_written_with_absolute_exec(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = pb.install_desktop_entry("/opt/packing-slips")
    text = p.read_text()
    assert 'Exec="/opt/packing-slips" %f' in text
    assert "Type=Application" in text
    assert p.name == "packing-slips.desktop"

def test_desktop_entry_quotes_path_with_spaces(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    p = pb.install_desktop_entry("/home/someone/Packing Logistics/dist/packing-slips")
    text = p.read_text()
    assert 'Exec="/home/someone/Packing Logistics/dist/packing-slips" %f' in text

def test_offer_is_remembered_after_decline(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pb.should_offer_desktop_entry() is True
    pb.remember_desktop_choice(False)
    assert pb.should_offer_desktop_entry() is False

def test_offer_not_made_after_install(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(pb, "_windows", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pb.should_offer_desktop_entry() is True
    pb.install_desktop_entry("/opt/packing-slips")
    assert pb.should_offer_desktop_entry() is False

def test_never_offer_on_windows(monkeypatch):
    monkeypatch.setattr(pb, "_windows", lambda: True)
    assert pb.should_offer_desktop_entry() is False
