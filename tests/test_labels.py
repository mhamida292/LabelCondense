from PIL import Image

import whatnot_slips as ws

def _img(mode, size, colour):
    return Image.new(mode, size, colour)

# --- a label that would print nothing is never a correct result -------------
# Sept 16 shipment 61 and Sept 20 shipment 77 both shipped a blank label
# because pdfimages wrote the artwork and its transparency mask at byte-equal
# sizes and `max(..., key=getsize)` broke the tie on unsorted directory order.
# The audit agreed with itself because it extracted the same way.

def test_a_blank_label_is_blank():
    assert ws.is_blank(_img("1", (120, 180), 1))

def test_a_missing_label_counts_as_blank():
    assert ws.is_blank(None)

def test_a_label_with_any_ink_at_all_is_not_blank():
    im = _img("1", (120, 180), 1)
    im.putpixel((7, 9), 0)
    assert not ws.is_blank(im)

# --- orientation -----------------------------------------------------------

def test_a_landscape_page_is_rotated_to_fill_the_portrait_sheet():
    assert ws._to_1bit(_img("L", (1800, 1200), 255)).size == (1200, 1800)

def test_an_already_portrait_page_is_left_alone():
    """Whatnot lays a landscape 6x4 First-Class label sideways on a portrait
    page, so a rendered page already carries the orientation the old
    extract-and-rotate path produced. Rotating again would squash it."""
    assert ws._to_1bit(_img("L", (1205, 1808), 255)).size == (1205, 1808)
