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
