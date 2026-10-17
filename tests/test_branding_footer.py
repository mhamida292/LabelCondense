import pytest

import branding
import whatnot_slips as ws

def sdir():
    return branding.settings_dir()

def test_footer_defaults_off_and_empty():
    b = branding.load(); assert (b.footer_enabled, b.footer) == (False, "")
    assert branding.active_footer() is None

def test_footer_round_trips_and_is_independent_of_branding():
    branding.save(branding.Brand(enabled=False, footer_enabled=True, footer="Live Tues 7pm"))
    assert branding.active_footer() == "Live Tues 7pm"
    assert branding.active() is None

def test_footer_text_kept_but_inactive_when_switched_off():
    branding.save(branding.Brand(footer_enabled=False, footer="Live Tues 7pm"))
    assert branding.load().footer == "Live Tues 7pm"
    assert branding.active_footer() is None

def test_footer_over_120_chars_is_refused():
    errs = branding.problems(branding.Brand(footer="a " * 61))
    assert "The footer is too long: it must fit on 2 lines." in errs

def test_wide_footer_under_120_chars_that_needs_3_lines_is_refused():
    assert len("W" * 100) <= 120 and not branding.footer_fits("W" * 100)

@pytest.mark.parametrize("word", ["To:", "From:", "Packing Slip", "Pick List"])
def test_footer_refuses_page_marker_words(word):
    assert any("footer can't contain" in e for e in
               branding.problems(branding.Brand(footer=f"see {word} here")))

def test_hand_edited_bad_footer_is_dropped_with_a_note():
    (sdir() / "settings.json").write_text('{"footer_enabled": true, "footer": "%s"}' % ("x" * 300))
    b = branding.load()
    assert b.footer == "" and any("footer" in n for n in b.notes)

def test_footer_with_emoji_and_newlines_uses_renderable_text():
    assert ws.footer_lines("Thanks!\n\U0001F389 Live Tues") == ["Thanks! Live Tues"]
    branding.save(branding.Brand(footer_enabled=True, footer="\U0001F389\n"))
    assert branding.active_footer() is None

def test_a_wrong_typed_footer_enabled_is_not_coerced():
    (sdir() / "settings.json").write_text('{"footer_enabled": "yes"}')
    b = branding.load()
    assert b.footer_enabled is False and b.notes

def test_footer_lines_empty_and_wrapped_to_two():
    assert ws.footer_lines("") == []
    assert len(ws.footer_lines("word " * 40)) == 2
