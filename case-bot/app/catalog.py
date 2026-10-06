"""Skinlar katalogi, case'lar va to'lov paketlari.

* `value` — skin qiymati Stars'da. Sotilganda shuncha Stars qaytadi (SELL_RATE_PERCENT).
  Haqiqiy Steam narxiga mos qilib qo'ying — Steam'ga chiqarilganda siz shu skinni sotib olib berasiz.
* Case narxi AVTOMATIK hisoblanadi: o'rtacha yutuq / CASE_RTP_PERCENT.
  Ya'ni faqat skin qiymati va og'irligini (weight) o'zgartirasiz — narx o'zi to'g'ri chiqadi.
* Rasm: bot'ga admin sifatida rasm yuboring, izohiga skin kalitini yozing (masalan `awp_asi`).
  Yoki `public/images/<kalit>.png` faylini repoga qo'ying.
"""
import math
import secrets

from app.config import CASE_RTP_PERCENT

rng = secrets.SystemRandom()

# Rarity: CS2 dagi ranglar bilan (frontendda ishlatiladi)
RARITIES = {
    "consumer":   {"label": "Consumer",   "color": "#B0C3D9"},
    "industrial": {"label": "Industrial", "color": "#5E98D9"},
    "milspec":    {"label": "Mil-Spec",   "color": "#4B69FF"},
    "restricted": {"label": "Restricted", "color": "#8847FF"},
    "classified": {"label": "Classified", "color": "#D32CE6"},
    "covert":     {"label": "Covert",     "color": "#EB4B4B"},
    "gold":       {"label": "★ Rare",     "color": "#E4AE39"},
}

# kalit: (nomi, rarity, qiymati Stars'da)
SKINS = {
    "cz75":         ("CZ75-Auto | Tread Plate",       "industrial", 8),
    "glock":        ("Glock-18 | Groundwater",        "industrial", 10),
    "tec9":         ("Tec-9 | Titanium Bit",          "milspec",    20),
    "p250":         ("P250 | Electric Hive",          "milspec",    25),
    "famas":        ("FAMAS | Neural Net",            "milspec",    30),
    "ssg08":        ("SSG 08 | Abyss",                "milspec",    35),
    "fiveseven":    ("Five-SeveN | Fowl Play",        "restricted", 70),
    "scar20":       ("SCAR-20 | Bloodsport",          "restricted", 90),
    "ak47_cartel":  ("AK-47 | Cartel",                "restricted", 110),
    "m4a4_space":   ("M4A4 | Desolate Space",         "classified", 250),
    "mp9_lily":     ("MP9 | Wild Lily",               "classified", 300),
    "deagle":       ("Desert Eagle | Kumicho Dragon", "classified", 350),
    "ak47_red":     ("AK-47 | Redline",               "classified", 400),
    "ak47_blood":   ("AK-47 | Bloodsport",            "covert",     700),
    "ak47_neon":    ("AK-47 | Neon Rider",            "covert",     900),
    "awp_hb":       ("AWP | Hyper Beast",             "covert",     1100),
    "m4a4_pos":     ("M4A4 | Poseidon",               "covert",     1800),
    "awp_asi":      ("AWP | Asiimov",                 "covert",     2500),
    "glock_fade":   ("Glock-18 | Fade",               "covert",     4000),
    "ak47_lotus":   ("AK-47 | Wild Lotus",            "gold",       25000),
    "karambit":     ("★ Karambit | Fade",             "gold",       45000),
    "butterfly":    ("★ Butterfly Knife | Doppler",   "gold",       50000),
    "m4a4_howl":    ("M4A4 | Howl",                   "gold",       60000),
    "awp_dl":       ("AWP | Dragon Lore",             "gold",       120000),
}

# Case tarkibi: (skin kaliti, og'irlik). Og'irlik qancha katta — shuncha tez-tez tushadi.
CASES = [
    {"id": "free", "name": "Kunlik bepul", "free": True, "items": [
        ("cz75", 6000), ("glock", 3000), ("tec9", 900), ("famas", 90), ("ak47_red", 10)]},
    {"id": "starter", "name": "Boshlang'ich", "badge": "Yangi o'yinchilar", "items": [
        ("cz75", 3000), ("glock", 3000), ("tec9", 2000), ("p250", 1200), ("famas", 500),
        ("ak47_cartel", 200), ("ak47_red", 70), ("awp_hb", 20), ("awp_asi", 10)]},
    {"id": "pistol", "name": "To'pponcha", "items": [
        ("glock", 3500), ("p250", 3000), ("fiveseven", 1800), ("deagle", 500),
        ("glock_fade", 40)]},
    {"id": "ak", "name": "AK-47", "badge": "Mashhur", "items": [
        ("ak47_cartel", 5000), ("ak47_red", 3000), ("ak47_blood", 1200), ("ak47_neon", 600),
        ("ak47_lotus", 15)]},
    {"id": "sniper", "name": "Snayper", "items": [
        ("ssg08", 5000), ("scar20", 3000), ("awp_hb", 900), ("awp_asi", 350), ("awp_dl", 5)]},
    {"id": "m4", "name": "M4A4", "items": [
        ("famas", 4000), ("m4a4_space", 3500), ("m4a4_pos", 800), ("m4a4_howl", 10)]},
    {"id": "knife", "name": "Pichoq", "badge": "Eng qimmat", "items": [
        ("ak47_neon", 4000), ("awp_asi", 3500), ("glock_fade", 1500), ("karambit", 120),
        ("butterfly", 100), ("awp_dl", 15)]},
]

# Stars paketlari: "stars" — to'lanadi, "bonus" — ustiga qo'shiladi
PACKAGES = {
    "s":  {"stars": 100,  "bonus": 0},
    "m":  {"stars": 500,  "bonus": 25},
    "l":  {"stars": 1000, "bonus": 75},
    "xl": {"stars": 5000, "bonus": 500},
}


# ── Yordamchilar ──────────────────────────────────────────────────────

def skin(key: str) -> dict | None:
    s = SKINS.get(key)
    if not s:
        return None
    name, rarity, value = s
    return {"key": key, "name": name, "rarity": rarity, "value": value}


_NAME_TO_KEY = {v[0].lower(): k for k, v in SKINS.items()}


def key_by_name(name: str) -> str | None:
    return _NAME_TO_KEY.get((name or "").strip().lower())


def _round_price(x: float) -> int:
    step = 1 if x < 100 else 5 if x < 200 else 10 if x < 1000 else 50 if x < 10000 else 100
    return max(step, math.ceil(x / step) * step)   # yuqoriga — RTP hech qachon oshib ketmaydi


def _ev(items) -> float:
    total = sum(w for _, w in items)
    return sum(SKINS[k][2] * w for k, w in items) / total


def _prepare():
    out = []
    for c in CASES:
        total = sum(w for _, w in c["items"])
        ev = _ev(c["items"])
        price = 0 if c.get("free") else _round_price(ev * 100 / CASE_RTP_PERCENT)
        out.append({
            **{k: v for k, v in c.items() if k != "items"},
            "price": price,
            "avg_value": round(ev, 1),
            "rtp": None if not price else round(ev / price * 100, 1),
            "items": sorted(
                [{**skin(k), "chance": round(w / total * 100, 3)} for k, w in c["items"]],
                key=lambda x: -x["value"]),
            "_pool": c["items"],
        })
    return out


CASE_LIST = _prepare()
CASE_BY_ID = {c["id"]: c for c in CASE_LIST}


def public_cases() -> list[dict]:
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in CASE_LIST]


def pick(case_id: str) -> dict:
    pool = CASE_BY_ID[case_id]["_pool"]
    key = rng.choices([k for k, _ in pool], weights=[w for _, w in pool], k=1)[0]
    return skin(key)


def validate() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "CASES: takroriy id"
    assert sum(1 for c in CASES if c.get("free")) <= 1, "Bepul case bittadan ko'p"
    for c in CASES:
        assert c["items"], f"{c['id']}: bo'sh case"
        for k, w in c["items"]:
            assert k in SKINS, f"{c['id']}: noma'lum skin '{k}'"
            assert w > 0, f"{c['id']}: og'irlik > 0 bo'lishi kerak"
    for k, (_, r, v) in SKINS.items():
        assert r in RARITIES, f"{k}: noma'lum rarity '{r}'"
        assert v > 0, f"{k}: qiymat > 0 bo'lishi kerak"
    for k, p in PACKAGES.items():
        assert p["stars"] >= 1, f"Paket {k}"
