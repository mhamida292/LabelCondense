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

@pytest.fixture(scope="session", autouse=True)
def windows_binaries():
    """Unfrozen on Windows, _bin() returns bare names like 'gs', which are not
    on PATH there. Point it at what fetch_windows_binaries.ps1 downloaded, and
    give gs its resource tree the way packaging/rthook_gs_env.py does."""
    pkg = pathlib.Path(__file__).resolve().parent.parent / "packaging"
    if os.name != "nt" or not (pkg / "bin").is_dir():
        yield
        return
    import whatnot_slips as ws
    res = pkg / "gs-resources"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ws, "_bin", lambda name: str(
            pkg / "bin" / ws._WIN_NAMES.get(name, name + ".exe")))
        mp.setenv("GS_LIB", os.pathsep.join(
            str(res / d) for d in ("Resource/Init", "lib", "iccprofiles")))
        yield
