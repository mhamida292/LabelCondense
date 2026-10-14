import os, pathlib, pytest

@pytest.fixture(scope="session")
def sample_pdf():
    p = os.environ.get("PACKING_TEST_PDF")
    if not p:
        pytest.skip("set PACKING_TEST_PDF to a real Whatnot export to run parity tests")
    path = pathlib.Path(p)
    if not path.is_file():
        pytest.skip(f"PACKING_TEST_PDF does not exist: {path}")
    return path

@pytest.fixture(scope="session")
def sku_pdf():
    p = os.environ.get("PACKING_SKU_PDF")
    if not p:
        pytest.skip("set PACKING_SKU_PDF to a Whatnot export that carries SKUs")
    path = pathlib.Path(p).expanduser()
    if not path.is_file():
        pytest.skip(f"PACKING_SKU_PDF does not exist: {path}")
    return path

@pytest.fixture(autouse=True)
def settings_in_tmp(tmp_path, monkeypatch):
    """No test may read or write the real user's branding settings."""
    monkeypatch.setenv("LABEL_CONDENSE_SETTINGS_DIR", str(tmp_path / "settings"))

@pytest.fixture(autouse=True)
def no_desktop_pickers(tmp_path, monkeypatch):
    """Tests never open kdialog/zenity, and never see the real Downloads."""
    import dialogs, recent
    monkeypatch.setattr(dialogs, "_native_tool", lambda: None)
    (tmp_path / "Downloads").mkdir(exist_ok=True)
    monkeypatch.setattr(recent, "downloads", lambda: tmp_path / "Downloads")

@pytest.fixture(scope="session", autouse=True)
def windows_binaries(tmp_path_factory):
    """Unfrozen, _bin() returns bare names ('gs', 'pdftotext') and relies on
    PATH. On Windows CI those live in packaging/bin, and gs is gswin64c.exe:
    put a gs.exe copy and packaging/bin on PATH, and give gs its resource
    tree the way packaging/rthook_gs_env.py does."""
    import shutil
    pkg = pathlib.Path(__file__).resolve().parent.parent / "packaging"
    if os.name != "nt" or not (pkg / "bin" / "gswin64c.exe").is_file():
        yield
        return
    gs = tmp_path_factory.mktemp("gs")
    shutil.copy(pkg / "bin" / "gswin64c.exe", gs / "gs.exe")
    shutil.copy(pkg / "bin" / "gsdll64.dll", gs)
    res = pkg / "gs-resources"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", os.pathsep.join([str(gs), str(pkg / "bin"),
                                           os.environ.get("PATH", "")]))
        mp.setenv("GS_LIB", os.pathsep.join(
            str(res / d) for d in ("Resource/Init", "lib", "iccprofiles", "fonts")))
        yield
