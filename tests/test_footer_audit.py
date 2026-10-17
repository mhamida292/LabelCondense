import synth
import whatnot_slips as ws

HOSTILE = "#1 $1.00 1 Item $1.00 SKU A"


def _src(tmp_path):
    return str(synth.make_export(tmp_path / "src.pdf", synth.sample())), str(tmp_path / "out.pdf")


def test_footer_build_passes_audit(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, footer="Live Tues 7pm")
    assert ws.verify(src, out, deep=True, footer="Live Tues 7pm").fail == []


def test_hostile_footer_does_not_fail_a_good_slip(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, footer=HOSTILE)
    assert ws.verify(src, out, deep=True, footer=HOSTILE).fail == []


def test_hostile_footer_does_not_pass_a_broken_slip(tmp_path, monkeypatch):
    src, out = _src(tmp_path)
    real = ws.build_rows

    def drop_first_number(grouped):
        blocks = real(grouped)
        for b in blocks:
            for _, ops in b:
                for i, op in enumerate(ops):
                    if "(#1)" in op:
                        ops[i] = op.replace("(#1)", "()")
        return blocks

    monkeypatch.setattr(ws, "build_rows", drop_first_number)
    ws.build(src, out, quiet=True, footer=HOSTILE)
    monkeypatch.undo()
    a = ws.verify(src, out, footer=HOSTILE)
    assert any("variant" in f[0] if isinstance(f, tuple) else "variant" in str(f)
               for f in a.fail)


def test_missing_footer_fails(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True)
    a = ws.verify(src, out, footer="Thanks")
    assert any("footer" in str(f) for f in a.fail)


def test_footer_without_branding_keeps_the_plain_header(tmp_path):
    src, out = _src(tmp_path)
    ws.build(src, out, quiet=True, brand=None, footer="Thanks")
    pages = [p for p in ws.pdf_pages(out) if "Packing Slip" in p]
    assert pages and all("Whatnot Packing Slip" in p and "Thanks" in p for p in pages)
    assert ws.verify(src, out, footer="Thanks").fail == []


def test_split_footer():
    body = "a\nb\n\nLive\nTues\n\n"
    assert ws.split_footer(body, ["Live", "Tues"]) == ("a\nb\n", True)
    assert ws.split_footer(body, ["Nope"]) == (body, False)
    assert ws.split_footer(body, []) == (body, True)
