import hashlib, json, pathlib, subprocess, tempfile
import pytest
import whatnot_slips as ws

BASELINE = pathlib.Path(__file__).parent / "baseline.json"

def semantic_fingerprint(pdf):
    """Timestamp-immune description of a built PDF."""
    pages = ws.pdf_pages(str(pdf))
    return {
        "pages": len(pages),
        "text_sha": hashlib.sha256("\f".join(pages).encode()).hexdigest(),
    }

def build_and_fingerprint(src, tmpdir):
    out = pathlib.Path(tmpdir) / "out.pdf"
    n, nsl, nlb = ws.build(str(src), str(out), quiet=True)
    audit = ws.verify(str(src), str(out), deep=False)
    fp = semantic_fingerprint(out)
    fp.update(shipments=n, slip_pages=nsl, labels=nlb,
              checks=audit.checks, failures=len(audit.fail))
    return fp

def test_build_matches_baseline(sample_pdf):
    if not BASELINE.exists():
        pytest.skip("no baseline recorded yet; run tests/record_baseline.py")
    with tempfile.TemporaryDirectory() as td:
        got = build_and_fingerprint(sample_pdf, td)
    assert got == json.loads(BASELINE.read_text())

def test_audit_passes_clean(sample_pdf):
    with tempfile.TemporaryDirectory() as td:
        fp = build_and_fingerprint(sample_pdf, td)
    assert fp["failures"] == 0
