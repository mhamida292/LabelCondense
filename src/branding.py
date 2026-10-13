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

@dataclass
class Brand:
    enabled: bool = False
    shop_name: str = ""
    message: str = DEFAULT_MESSAGE
    logo: Image.Image | None = None
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
    lines = ws.wrap(text, ws.MSG_W, ws.MSG_SIZE)
    return (len(lines) <= MESSAGE_LINES
            and all(ws.sw(ln, ws.MSG_SIZE) <= ws.MSG_W for ln in lines))

def name_fits(name):
    return ws.shop_name_size(name) is not None

def problems(b):
    """Why `b` can't be saved, in words for the person; [] when it can.
    Refusing here is what keeps anything from being cut off on paper."""
    out = []
    if not message_fits(b.message):
        out.append("The message is too long: it must fit on 2 lines.")
    if not name_fits(b.shop_name):
        out.append("The shop name is too long to fit in the logo space.")
    return out

def load():
    b = Brand()
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
        b.enabled = bool(raw.get("brand_enabled", False))
        b.shop_name = str(raw.get("shop_name", ""))
        b.message = str(raw.get("message", DEFAULT_MESSAGE))
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
    if _logo_path().exists():
        try:
            with Image.open(_logo_path()) as im:
                b.logo = im.convert("1")
        except (OSError, ValueError) as exc:
            b.notes.append(f"logo unreadable ({exc}); showing the shop name instead")
    return b

def active():
    """The brand to print with, or None when branding is switched off."""
    b = load()
    return b if b.enabled else None

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
                       "message": b.message}, indent=2)
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
