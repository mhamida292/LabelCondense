import synth
import whatnot_slips as ws

def test_synthetic_export_round_trips_through_build_and_verify(tmp_path):
    src = synth.make_export(tmp_path / "src.pdf", synth.sample())
    out = tmp_path / "out.pdf"
    ws.build(str(src), str(out), quiet=True)
    a = ws.verify(str(src), str(out), deep=True)
    assert a.fail == [] and a.checks > 50

def test_synthetic_source_parses_like_a_real_one(tmp_path):
    ships = synth.sample()
    _, data = ws.load(str(synth.make_export(tmp_path / "s.pdf", ships)))
    assert [len(items) for _, _, items in data] == [len(s.items) for s in ships]
    assert [ship["track"] for _, ship, _ in data] == [s.track for s in ships]
    assert any(it["sku"] for _, _, items in data for it in items)
