"""The shop's branding for the slip header: what it says, where it is kept,
and turning a chosen image into what the thermal head will print. Knows
nothing about tkinter; drawing it is whatnot_slips' job."""
import json, os, pathlib, tempfile
from dataclasses import dataclass, field

from PIL import Image, ImageOps

import logstore
import whatnot_slips as ws

DEFAULT_MESSAGE = "Thank you for shopping with us!"
LOGO_PX = (450, 150)             # the 108 x 36 pt logo box at 300 dpi
MESSAGE_LINES = 2
MESSAGE_MAX = 60                 # about two lines beside the logo box
FOOTER_MAX = 120
FOOTER_LINES = 2
PAGE_MARKERS = ("To:", "From:", "Packing Slip", "Pick List")

@dataclass
class Brand:
    enabled: bool = False
    shop_name: str = ""
    message: str = DEFAULT_MESSAGE
    logo: Image.Image | None = None
    footer_enabled: bool = False
    footer: str = ""
    notes: list = field(default_factory=list)   # why something fell back

def settings_dir():
    override = os.environ.get("LABEL_CONDENSE_SETTINGS_DIR")
    d = pathlib.Path(override) if override else logstore.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d

def _settings_path(): return settings_dir() / "settings.json"
def _logo_path():     return settings_dir() / "logo.png"

def message_fits(text):
    text = ws.renderable(text)
    if not text:
        return True
    if len(text) > MESSAGE_MAX:
        return False
    lines = ws.wrap(text, ws.MSG_W, ws.MSG_SIZE)
    return (len(lines) <= MESSAGE_LINES
            and all(ws.sw(ln, ws.MSG_SIZE) <= ws.MSG_W for ln in lines))

def footer_fits(text):
    text = ws.renderable(text)
    if not text:
        return True
    if len(text) > FOOTER_MAX:
        return False
    lines = ws.wrap(text, ws.FOOT_W, ws.FOOT_SIZE, bold=False)
    return (len(lines) <= FOOTER_LINES
            and all(ws.sw(ln, ws.FOOT_SIZE) <= ws.FOOT_W for ln in lines))

def _footer_has_marker(text):
    text = ws.renderable(text)
    return any(m in text for m in PAGE_MARKERS)

def name_fits(name):
    return ws.shop_name_size(name) is not None

def _has_anchor(text):
    return "To:" in text or "From:" in text

def problems(b):
    """Why `b` can't be saved, in words for the person; [] when it can.
    Refusing here is what keeps anything from being cut off on paper."""
    out = []
    if not message_fits(b.message):
        out.append("The message is too long: it must fit on 2 lines.")
    if not name_fits(b.shop_name):
        out.append("The shop name is too long to fit in the logo space.")
    if _has_anchor(b.shop_name) or _has_anchor(b.message):
        out.append("The shop name and message can't contain \"To:\" or \"From:\" "
                   "\u2014 the slip uses those words to find the address.")
    if not footer_fits(b.footer):
        out.append("The footer is too long: it must fit on 2 lines.")
    if _footer_has_marker(b.footer):
        out.append("The footer can't contain \"To:\", \"From:\", \"Packing Slip\" "
                   "or \"Pick List\" \u2014 the app uses those words to find each "
                   "part of the page.")
    return out

def load():
    """Never raises: it runs at app start and at the start of every run."""
    b = Brand()
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not a settings object")
        for key, attr, kind in (("brand_enabled", "enabled", bool),
                                ("shop_name", "shop_name", str),
                                ("message", "message", str),
                                ("footer_enabled", "footer_enabled", bool),
                                ("footer", "footer", str)):
            if key not in raw:
                continue
            if isinstance(raw[key], kind):
                setattr(b, attr, raw[key])
            else:
                b.notes.append(f"branding {key} has the wrong type; using the default")
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError) as exc:
        b.notes.append(f"branding settings unreadable ({exc}); using defaults")
    if not message_fits(b.message):
        b.notes.append("branding message too long for 2 lines; not printed")
        b.message = ""
    if not name_fits(b.shop_name):
        b.notes.append("shop name too long to fit; not printed")
        b.shop_name = ""
    if not footer_fits(b.footer):
        b.notes.append("footer too long for 2 lines; not printed")
        b.footer = ""
    elif _footer_has_marker(b.footer):
        b.notes.append("footer contains a page-marker word; not printed")
        b.footer = ""
    for attr, what in (("shop_name", "shop name"), ("message", "message")):
        if _has_anchor(getattr(b, attr)):
            b.notes.append(f'branding {what} contains "To:" or "From:"; not printed')
            setattr(b, attr, "")
    try:
        path = _logo_path()
        if path.exists():
            with Image.open(path) as im:
                b.logo = im.convert("1")
    except Exception as exc:    # a stored logo must never stop a run
        b.notes.append(f"logo unreadable ({exc}); showing the shop name instead")
    return b

def active():
    """The brand to print with, or None when branding is switched off."""
    b = load()
    return b if b.enabled else None

def active_footer():
    """The footer to print, or None; independent of header branding."""
    b = load()
    text = ws.renderable(b.footer) if b.footer_enabled else ""
    return text or None

def _replace_atomically(path, write):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise

def save(b):
    errs = problems(b)
    if errs:
        raise ValueError(" ".join(errs))
    data = json.dumps({"brand_enabled": b.enabled, "shop_name": b.shop_name,
                       "message": b.message,
                       "footer_enabled": b.footer_enabled, "footer": b.footer}, indent=2)
    _replace_atomically(_settings_path(),
                        lambda tmp: pathlib.Path(tmp).write_text(data, encoding="utf-8"))
    if b.logo is None:
        _logo_path().unlink(missing_ok=True)
    else:
        _replace_atomically(_logo_path(), lambda tmp: b.logo.save(tmp, "PNG"))

def import_logo(path):
    """Any image Pillow reads, turned into exactly what will print:
    transparency flattened onto white, trimmed to its ink, fitted to the logo
    box at 300 dpi, then thresholded to pure black and white like the labels."""
    with Image.open(path) as im:
        im.load()
        rgba = im.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat.alpha_composite(rgba)
    g = flat.convert("L")
    box = ImageOps.invert(g).point(lambda p: 255 if p > 127 else 0).getbbox()
    if box is None:
        raise ValueError("The image is blank: nothing in it would print.")
    g = g.crop(box)
    r = min(LOGO_PX[0] / g.width, LOGO_PX[1] / g.height)
    g = g.resize((max(1, round(g.width * r)), max(1, round(g.height * r))),
                 Image.LANCZOS)
    return g.point(lambda p: 255 if p >= 128 else 0, "1")
