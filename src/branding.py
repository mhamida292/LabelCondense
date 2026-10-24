"""The shop's branding for the slip header: what it says, where it is kept,
and turning a chosen image into what the thermal head will print. Knows
nothing about tkinter; drawing it is whatnot_slips' job.

Branding lives in profiles, one per brand, so different shows can print
different headers without retyping them. The first profile ("Default") is
kept in settings.json + logo.png exactly as before profiles existed; the
others are profiles/<id>.json + profiles/<id>.png. A profile's id never
changes, so renaming one moves no files; the chosen one is remembered in
prefs.json."""
import json, os, pathlib, re, tempfile
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
DEFAULT_ID = ""                  # the profile stored in settings.json + logo.png
DEFAULT_NAME = "Default"
PROFILE_NAME_MAX = 40

@dataclass
class Brand:
    enabled: bool = False
    shop_name: str = ""
    message: str = DEFAULT_MESSAGE
    logo: Image.Image | None = None
    footer_enabled: bool = False
    footer: str = ""
    notes: list = field(default_factory=list)   # why something fell back
    profile: str = DEFAULT_NAME                 # which profile it came from

def settings_dir():
    override = os.environ.get("LABEL_CONDENSE_SETTINGS_DIR")
    d = pathlib.Path(override) if override else logstore.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d

def _settings_path(pid=DEFAULT_ID):
    return settings_dir() / "settings.json" if not pid else _profiles_dir() / f"{pid}.json"

def _logo_path(pid=DEFAULT_ID):
    return settings_dir() / "logo.png" if not pid else _profiles_dir() / f"{pid}.png"

def _profiles_dir():
    return settings_dir() / "profiles"

# ------------------------------------------------------------------ profiles
RE_PID = re.compile(r'^p\d+$')

def _raw(pid):
    """A profile's saved fields as stored, or {} if missing or unreadable."""
    try:
        raw = json.loads(_settings_path(pid).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}

def _name_key(pid):
    return "profile_name" if not pid else "name"

def profile_name(pid):
    name = _raw(pid).get(_name_key(pid))
    return name.strip() if isinstance(name, str) and name.strip() else (
        DEFAULT_NAME if not pid else pid)

def profiles():
    """[(id, name)]: Default first, then the rest by name."""
    try:
        extra = [f.stem for f in _profiles_dir().glob("p*.json") if RE_PID.match(f.stem)]
    except OSError:
        extra = []
    rest = sorted(((pid, profile_name(pid)) for pid in extra), key=lambda p: p[1].lower())
    return [(DEFAULT_ID, profile_name(DEFAULT_ID))] + rest

def profile_id(name):
    """The id of the profile called `name` (any case), or None."""
    for pid, n in profiles():
        if n.lower() == name.strip().lower():
            return pid
    return None

def _prefs_file():
    return settings_dir() / "prefs.json"

def current_profile():
    """The id of the profile the last run used (or the app last showed)."""
    try:
        pid = json.loads(_prefs_file().read_text(encoding="utf-8")).get("profile", DEFAULT_ID)
    except (OSError, ValueError, AttributeError):
        pid = DEFAULT_ID
    if not isinstance(pid, str) or (pid and not _settings_path(pid).exists()):
        return DEFAULT_ID
    return pid

def set_current_profile(pid):
    import recent                  # lazily: recent imports this module
    recent.set_pref("profile", pid)

def name_problem(name, pid=None):
    """Why `name` can't name a profile (pid: the one being renamed), or None."""
    name = name.strip()
    if not name:
        return "Give the profile a name."
    if len(name) > PROFILE_NAME_MAX:
        return f"Profile names can be up to {PROFILE_NAME_MAX} characters."
    other = profile_id(name)
    if other is not None and other != pid:
        return f"There is already a profile called {name}."
    return None

def create_profile(name, copy_from=None):
    """A new profile called `name`, starting as a copy of `copy_from` (an id)
    or of nothing. -> its id."""
    err = name_problem(name)
    if err:
        raise ValueError(err)
    _profiles_dir().mkdir(parents=True, exist_ok=True)
    taken = {pid for pid, _ in profiles()}
    pid = next(f"p{k}" for k in range(1, 10000) if f"p{k}" not in taken)
    b = load(copy_from) if copy_from is not None else Brand()
    b.notes = []
    _write(pid, b, name.strip())
    return pid

def rename_profile(pid, name):
    err = name_problem(name, pid)
    if err:
        raise ValueError(err)
    raw = _raw(pid); raw[_name_key(pid)] = name.strip()
    data = json.dumps(raw, indent=2)
    _replace_atomically(_settings_path(pid),
                        lambda tmp: pathlib.Path(tmp).write_text(data, encoding="utf-8"))

def delete_profile(pid):
    """Remove a profile. Default can't go: it is what everything falls back to."""
    if not pid:
        raise ValueError("The Default profile can't be deleted.")
    _settings_path(pid).unlink(missing_ok=True)
    _logo_path(pid).unlink(missing_ok=True)
    if current_profile() == pid:
        set_current_profile(DEFAULT_ID)

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

def load(pid=None):
    """A profile's branding (None: the current profile). Never raises: it runs
    at app start and at the start of every run."""
    if pid is None:
        pid = current_profile()
    b = Brand(profile=profile_name(pid))
    try:
        raw = json.loads(_settings_path(pid).read_text(encoding="utf-8"))
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
        path = _logo_path(pid)
        if path.exists():
            with Image.open(path) as im:
                b.logo = im.convert("1")
    except Exception as exc:    # a stored logo must never stop a run
        b.notes.append(f"logo unreadable ({exc}); showing the shop name instead")
    return b

def active(pid=None):
    """The brand to print with, or None when branding is switched off."""
    b = load(pid)
    return b if b.enabled else None

def active_footer(pid=None):
    """The footer to print, or None; independent of header branding."""
    b = load(pid)
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

def save(b, pid=None):
    """Save `b` into a profile (None: the current one), keeping its name."""
    if pid is None:
        pid = current_profile()
    errs = problems(b)
    if errs:
        raise ValueError(" ".join(errs))
    name = _raw(pid).get(_name_key(pid))
    _write(pid, b, name if isinstance(name, str) else None)

def _write(pid, b, name):
    fields = {"brand_enabled": b.enabled, "shop_name": b.shop_name,
              "message": b.message,
              "footer_enabled": b.footer_enabled, "footer": b.footer}
    if name:
        fields[_name_key(pid)] = name
    data = json.dumps(fields, indent=2)
    _replace_atomically(_settings_path(pid),
                        lambda tmp: pathlib.Path(tmp).write_text(data, encoding="utf-8"))
    if b.logo is None:
        _logo_path(pid).unlink(missing_ok=True)
    else:
        _replace_atomically(_logo_path(pid), lambda tmp: b.logo.save(tmp, "PNG"))

# What the logo box needs, in words an image generator follows. Sizes come
# from the box itself: 108 x 36 pt (1.5 x 0.5 in, 3:1) printed by a 203 dpi
# thermal head, so a stroke under ~3 dots or text under ~1/8 in is lost.
PROMPT_PX = (1350, 450)          # 3:1 at 900 px/in: a 15 px stroke is ~3 dots

def logo_prompt(shop_name=""):
    """A copy-pastable prompt for an AI image tool that yields a logo the
    slip prints well."""
    name = ws.renderable(shop_name) or "[your shop name]"
    w, h = PROMPT_PX
    return (
        f'Design a logo for a shop called "{name}". It will be printed on '
        f'4x6 inch shipping labels by a black-and-white thermal printer, in a '
        f'space 1.5 inches wide and 0.5 inches tall.\n\n'
        f'- Canvas: {w} x {h} pixels (a wide 3:1 rectangle), plain white background.\n'
        f'- Pure black on white only: no grey, colour, gradients, shadows, '
        f'textures or transparency.\n'
        f'- Bold, simple shapes. Every line and gap at least 15 pixels thick; '
        f'no fine detail, hairlines or small text.\n'
        f'- If the shop name is included, use a heavy, simple sans-serif at '
        f'least 120 pixels tall, and keep it to one or two short lines.\n'
        f'- Fill the canvas with a small margin; no border or frame around it.\n'
        f'- Deliver it as a PNG at exactly {w} x {h} pixels.')

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
