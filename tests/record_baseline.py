"""Record the current build's fingerprint, BEFORE any refactor.
Usage: PACKING_TEST_PDF=/path/to/export.pdf .venv/bin/python tests/record_baseline.py
"""
import json, os, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from test_parity import build_and_fingerprint

src = pathlib.Path(os.environ["PACKING_TEST_PDF"])
with tempfile.TemporaryDirectory() as td:
    fp = build_and_fingerprint(src, td)
out = pathlib.Path(__file__).parent / "baseline.json"
out.write_text(json.dumps(fp, indent=2, sort_keys=True) + "\n")
print("recorded", fp)
