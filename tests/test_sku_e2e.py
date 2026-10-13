import tempfile, pathlib
import whatnot_slips as ws

def test_oct13_export_builds_with_skus_and_passes_the_audit(sku_pdf):
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out.pdf"
        ws.build(str(sku_pdf), str(out), quiet=True)
        audit = ws.verify(str(sku_pdf), str(out), deep=False)
        text = "\f".join(ws.pdf_pages(str(out)))
    assert audit.fail == []
    assert "[TB200-477] CRUNCHY LOBSTER" in ws.renderable(text)
    assert "SKU ZW-112B" not in text           # the old leak
    assert "[ZW-112B] JUMBO CRUNCHY" in ws.renderable(text)
