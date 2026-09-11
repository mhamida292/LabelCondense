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
