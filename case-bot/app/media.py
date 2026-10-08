"""Media (rasm va ovoz) kalitlari va rasmlarni avtomatik moslash.

Admin botga rasm yuborganda u avtomatik:
  1) to'g'ri buriladi (telefon EXIF),
  2) chetidagi bo'sh joy kesiladi (shaffof fon yoki bir xil rangli fon — masalan qora),
  3) eng uzun tomoni 640 px gacha kichraytiriladi,
  4) WebP formatiga o'giriladi (sifat saqlanadi, hajm 5–10 baravar kichrayadi).
Natijada qanday rasm yuborilmasin, ilovada o'z joyiga to'g'ri tushadi va tez yuklanadi.
"""
import io
import os

from PIL import Image, ImageChops, ImageOps

from app.catalog import CASE_LIST, SKINS

Image.MAX_IMAGE_PIXELS = 40_000_000  # juda katta (zararli) rasmlardan himoya

GAMES = {"upgrade": "Upgrade", "contract": "Shartnoma", "crash": "Crash", "dice": "Dice"}

# Ovoz kalitlari: kalit → tavsif
SOUNDS = {
    "snd_tick":    "Case aylanganda har skin o'tgandagi «tiq»",
    "snd_spin":    "Case ochila boshlaganda",
    "snd_drop":    "Oddiy skin tushganda",
    "snd_win":     "Yaxshi skin tushganda (Classified)",
    "snd_rare":    "Juda qimmat skin (Covert / ★)",
    "snd_unlock":  "Seyf qulfi ochilganda",
    "snd_ambient": "Yuklanish ekranidagi fon ovozi (takrorlanadi)",
    "snd_click":   "Tugmalar bosilganda",
    "snd_lose":    "O'yinda yutqazganda",
    "snd_fly":     "Crash: samolyot uchayotganda (takrorlanadi)",
    "snd_crash":   "Crash: samolyot uchib ketganda",
    "snd_cashout": "Crash: pul yechib olinganda",
}

IMAGE_KEYS = set(SKINS) | {"case_" + c["id"] for c in CASE_LIST} | {"game_" + g for g in GAMES} | {"logo", "crash_plane"}
SOUND_KEYS = set(SOUNDS)
ALL_KEYS = IMAGE_KEYS | SOUND_KEYS

MAX_IMAGE_IN = 10 * 1024 * 1024
MAX_SOUND_IN = 2 * 1024 * 1024
_MAX_SIDE = {"skin": 640, "case": 720, "game": 900, "logo": 512, "plane": 420}

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "images")
STATIC_EXT = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".svg": "image/svg+xml", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
              ".m4a": "audio/mp4"}


def kind(key: str) -> str:
    if key in SOUND_KEYS:
        return "sound"
    if key.startswith("case_"):
        return "case"
    if key.startswith("game_"):
        return "game"
    if key == "logo":
        return "logo"
    if key == "crash_plane":
        return "plane"
    return "skin"


def static_keys() -> set[str]:
    out = set()
    if os.path.isdir(STATIC_DIR):
        for f in os.listdir(STATIC_DIR):
            k, ext = os.path.splitext(f)
            if ext.lower() in STATIC_EXT and k in ALL_KEYS:
                out.add(k)
    return out


def _trim(im: Image.Image) -> Image.Image:
    """Chetdagi bo'sh joyni kesadi. Juda ko'p kesilsa (xato bo'lishi mumkin) — tegmaydi."""
    w, h = im.size
    alpha = im.getchannel("A")
    if alpha.getextrema()[0] < 250:                       # shaffof joylari bor
        bbox = alpha.point(lambda a: 255 if a > 16 else 0).getbbox()
    else:                                                  # fon — burchaklardagi rang
        rgb = im.convert("RGB")
        corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
        diff = ImageChops.difference(rgb, Image.new("RGB", (w, h), bg)).convert("L")
        bbox = diff.point(lambda d: 255 if d > 38 else 0).getbbox()
    if not bbox:
        return im
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if bw * bh < 0.04 * w * h:
        return im
    pad = int(max(bw, bh) * 0.04)
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad))
    return im.crop(bbox)


def normalize_image(data: bytes, key: str) -> tuple[bytes, str]:
    """Rasmni moslaydi va (baytlar, mime) qaytaradi. Rasm bo'lmasa ValueError."""
    if len(data) > MAX_IMAGE_IN:
        raise ValueError("too_big")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError("not_image") from e
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im = _trim(im)
    side = _MAX_SIDE.get(kind(key), 640)
    im.thumbnail((side, side), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=86, method=4)
    return out.getvalue(), "image/webp"


_AUDIO_MAGIC = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"OggS", b"RIFF", b"fLaC")


def check_sound(data: bytes, mime: str) -> str:
    if len(data) > MAX_SOUND_IN:
        raise ValueError("too_big")
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data.startswith(_AUDIO_MAGIC):
        return "audio/mpeg"
    if (mime or "").startswith("audio/"):
        return mime
    raise ValueError("not_audio")
