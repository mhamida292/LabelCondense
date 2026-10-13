import json, os
import pytest
from PIL import Image

import branding
import logstore
import whatnot_slips as ws

def sdir():
    return branding.settings_dir()

# --- where things live -----------------------------------------------------

def test_settings_dir_honours_the_test_override(tmp_path):
    assert sdir() == tmp_path / "settings" and sdir().is_dir()

def test_log_dir_still_sits_under_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("PACKING_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "xdg"))
    assert logstore.log_dir() == logstore.data_dir() / "logs"

# --- load / save -----------------------------------------------------------

def test_defaults_when_nothing_is_saved():
    b = branding.load()
    assert (b.enabled, b.shop_name, b.message, b.logo, b.notes) == \
           (False, "", "Thank you for shopping with us!", None, [])
    assert branding.active() is None

def test_round_trip():
    branding.save(branding.Brand(enabled=True, shop_name="Squish Co",
                                 message="Thanks!"))
    b = branding.load()
    assert (b.enabled, b.shop_name, b.message) == (True, "Squish Co", "Thanks!")
    assert branding.active() is not None

def test_save_leaves_no_temp_files():
    branding.save(branding.Brand(enabled=True))
    assert sorted(p.name for p in sdir().iterdir()) == ["settings.json"]

@pytest.mark.parametrize("junk", ["{not json", "[1, 2]", ""])
def test_corrupt_settings_fall_back_to_defaults_with_a_note(junk):
    (sdir() / "settings.json").write_text(junk)
    b = branding.load()
    assert b.enabled is False and b.message == branding.DEFAULT_MESSAGE
    assert len(b.notes) == 1 and "settings" in b.notes[0]

def test_hand_edited_overlong_message_is_dropped_not_truncated():
    (sdir() / "settings.json").write_text(json.dumps(
        {"brand_enabled": True, "shop_name": "", "message": "word " * 80}))
    b = branding.load()
    assert b.message == "" and "too long" in b.notes[0]

def test_save_refuses_an_overlong_message():
    with pytest.raises(ValueError, match="2 lines"):
        branding.save(branding.Brand(enabled=True, message="word " * 80))
    assert not (sdir() / "settings.json").exists()

def test_save_refuses_a_shop_name_that_cannot_fit():
    with pytest.raises(ValueError, match="shop name"):
        branding.save(branding.Brand(enabled=True, shop_name="W" * 40))

# --- fitting rules ---------------------------------------------------------

def test_default_message_fits():
    assert branding.message_fits(branding.DEFAULT_MESSAGE)

def test_message_fit_boundary():
    two = "Thank you for shopping with us! Follow us for restocks"
    assert branding.message_fits(two)
    assert len(ws.wrap(two, ws.MSG_W, ws.MSG_SIZE)) == 2
    assert not branding.message_fits(two + " every single week, friends!")

def test_a_single_unbreakable_word_wider_than_the_band_does_not_fit():
    assert not branding.message_fits("W" * 40)

def test_shop_name_size_shrinks_then_gives_up():
    assert ws.shop_name_size("Squish") == 16
    assert 8 <= ws.shop_name_size("Squishy Collectibles Co") < 16
    assert ws.shop_name_size("W" * 40) is None

# --- logo ------------------------------------------------------------------

def _save(tmp_path, im, name="logo.png"):
    p = tmp_path / name; im.save(p); return p

def test_logo_is_trimmed_fitted_and_made_one_bit(tmp_path):
    im = Image.new("RGB", (3000, 3000), "white")
    im.paste((200, 30, 30), (1000, 1300, 2000, 1700))   # red bar, 1000 x 400
    out = branding.import_logo(_save(tmp_path, im))
    assert out.mode == "1"
    assert out.size == (375, 150)                       # 2.5:1, height-bound
    assert out.getpixel((10, 10)) == 0                  # red became black

def test_transparent_background_becomes_white(tmp_path):
    im = Image.new("RGBA", (600, 200), (0, 0, 0, 0))    # transparent *black*
    im.paste((0, 0, 0, 255), (100, 50, 500, 150))
    out = branding.import_logo(_save(tmp_path, im))
    assert out.size == (450, 112)              # 112.5 rounds to even
    assert any(p == 255 for p in out.get_flattened_data()) is False  # trimmed to the ink

def test_a_tiny_logo_is_scaled_up(tmp_path):
    im = Image.new("L", (30, 10), 0)
    assert branding.import_logo(_save(tmp_path, im)).size == (450, 150)

def test_a_blank_image_is_refused(tmp_path):
    with pytest.raises(ValueError, match="blank"):
        branding.import_logo(_save(tmp_path, Image.new("RGB", (300, 100), "white")))

def test_a_non_image_is_refused(tmp_path):
    p = tmp_path / "x.png"; p.write_text("not an image")
    with pytest.raises(OSError):
        branding.import_logo(p)

def test_logo_is_saved_with_settings_and_removed_with_none(tmp_path):
    logo = branding.import_logo(_save(tmp_path, Image.new("L", (300, 100), 0)))
    branding.save(branding.Brand(enabled=True, logo=logo))
    assert branding.load().logo.size == logo.size
    branding.save(branding.Brand(enabled=True, logo=None))
    assert branding.load().logo is None
    assert not (sdir() / "logo.png").exists()

def test_unreadable_stored_logo_falls_back_with_a_note():
    branding.save(branding.Brand(enabled=True, shop_name="Squish"))
    (sdir() / "logo.png").write_text("corrupt")
    b = branding.load()
    assert b.logo is None and "logo" in b.notes[0]
