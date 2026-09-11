import whatnot_slips as ws

def test_audit_text_matches_report(capsys):
    a = ws.Audit()
    a.ok(True, "fine")
    a.ok(False, "broken", "detail here")
    text = a.text("AUDIT")
    ok = a.report("AUDIT")
    printed = capsys.readouterr().out
    assert ok is False
    assert text.strip() == printed.strip()
    assert "assertions run : 2" in text
    assert "failures       : 1" in text
    assert "FAIL broken: detail here" in text

def test_audit_text_clean_run():
    a = ws.Audit()
    a.ok(True, "fine")
    assert "failures       : 0" in a.text("AUDIT")

def test_build_reports_progress(sample_pdf, tmp_path):
    seen = []
    out = tmp_path / "o.pdf"
    ws.build(str(sample_pdf), str(out), quiet=True,
             progress=lambda d, t, s: seen.append((d, t, s)))
    assert seen, "progress callback was never called"
    assert all(s == "building slips" for _, _, s in seen)
    assert [d for d, _, _ in seen] == sorted(d for d, _, _ in seen)
    assert seen[-1][0] == seen[-1][1]          # reaches the total
    assert seen[-1][1] > 0

def test_verify_reports_progress(sample_pdf, tmp_path):
    out = tmp_path / "o.pdf"
    ws.build(str(sample_pdf), str(out), quiet=True)
    seen = []
    ws.verify(str(sample_pdf), str(out), deep=True,
              progress=lambda d, t, s: seen.append((d, t, s)))
    assert seen
    assert all(s == "checking labels" for _, _, s in seen)
    assert seen[-1][0] == seen[-1][1]
