"""Steam Trade URL tekshiruvi.

1) Format: https://steamcommunity.com/tradeoffer/new/?partner=<raqam>&token=<8 belgi>
2) partner → SteamID64 hisoblanadi va Steam'dan ochiq profil (nomi, avatari) olinadi —
   foydalanuvchi o'z akkauntini ko'rib tasdiqlaydi.
Eslatma: token'ning to'g'riligini faqat haqiqiy trade yuborib tekshirish mumkin (Steam API cheklovi).
"""
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_STEAM64_BASE = 76561197960265728
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{6,12}$")


class SteamError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_trade_url(url: str) -> tuple[str, int, str]:
    """(toza_url, partner, token) qaytaradi yoki SteamError('invalid_url')."""
    url = (url or "").strip().strip('"').strip("'")
    if not url or len(url) > 300:
        raise SteamError("invalid_url")
    if url.startswith("steamcommunity.com"):
        url = "https://" + url
    try:
        p = urlparse(url)
    except ValueError:
        raise SteamError("invalid_url")
    q = parse_qs(p.query)
    if (p.scheme not in ("https", "http") or p.netloc.lower() not in ("steamcommunity.com", "www.steamcommunity.com")
            or p.path.rstrip("/") != "/tradeoffer/new" or "partner" not in q or "token" not in q):
        raise SteamError("invalid_url")
    partner, token = q["partner"][0], q["token"][0]
    if not partner.isdigit() or not 0 < int(partner) < 2**32 or not _TOKEN_RE.match(token):
        raise SteamError("invalid_url")
    clean = f"https://steamcommunity.com/tradeoffer/new/?partner={int(partner)}&token={token}"
    return clean, int(partner), token


def to_id64(partner: int) -> str:
    return str(_STEAM64_BASE + partner)


def parse_profile_xml(text: str) -> dict | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if root.tag != "profile" or root.find("error") is not None:
        return None
    name = (root.findtext("steamID") or "").strip()
    avatar = (root.findtext("avatarMedium") or root.findtext("avatarFull") or "").strip()
    if avatar and not avatar.startswith("https://"):
        avatar = ""
    return {"name": name[:64] or None, "avatar": avatar or None}


async def fetch_profile(id64: str) -> dict | None:
    """Ochiq profil ma'lumoti. Profil topilmasa SteamError('steam_not_found'), tarmoq xatosi bo'lsa None."""
    url = f"https://steamcommunity.com/profiles/{id64}/?xml=1"
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 CaseVault"}) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        logger.warning("Steam profilini olib bo'lmadi: %s", e)
        return None
    if r.status_code != 200:
        return None
    prof = parse_profile_xml(r.text)
    if prof is None:
        if "<error>" in r.text:
            raise SteamError("steam_not_found")
        return None
    return prof
