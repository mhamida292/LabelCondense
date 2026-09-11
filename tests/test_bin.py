import os, subprocess, sys
import whatnot_slips as ws

def test_unfrozen_returns_bare_name(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert ws._bin("gs") == "gs"
    assert ws._bin("pdftotext") == "pdftotext"

def test_frozen_posix_uses_bundle_bin(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/bundle", raising=False)
    monkeypatch.setattr(os, "name", "posix")
    assert ws._bin("gs") == os.path.join("/bundle", "bin", "gs")

def test_frozen_windows_maps_ghostscript_name(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\bundle", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    assert ws._bin("gs").endswith("gswin64c.exe")
    assert ws._bin("pdftotext").endswith("pdftotext.exe")

def test_spawn_passes_through_and_checks(tmp_path):
    r = ws._spawn([sys.executable, "-c", "print('hi')"], capture_output=True, text=True)
    assert r.stdout.strip() == "hi"

def test_spawn_raises_on_failure():
    import pytest
    with pytest.raises(subprocess.CalledProcessError):
        ws._spawn([sys.executable, "-c", "raise SystemExit(3)"])
