"""Case'lar, sovg'alar va to'lov paketlari.

Muhim: `value` — skinning ichki qiymati (Stars hisobida). Sotilganda
SELL_RATE_PERCENT foizi balansga qaytadi. Server ishga tushganda har bir
case'ning o'rtacha qaytimi (RTP) logga yoziladi — narxlarni shunga qarab sozlang.
"""
import secrets

_rng = secrets.SystemRandom()

CASES = [
    {
        "id": "budget", "name": "Budget", "price": 750,
        "image": "images/case_budget.png", "emoji": "🔫",
        "description": "Kichik xavf, katta potensial — yangi boshlovchilar uchun",
        "filter": ["all", "tematik", "budget"], "color": "#00E676",
    },
    {
        "id": "eco", "name": "Eco", "price": 2500,
        "image": "images/case_eco.png", "emoji": "⚡",
        "description": "Eco roundlari uchun — past narxda yuqori qiymatli qurollar",
        "filter": ["all", "tematik"], "color": "#4DC8FF",
    },
    {
        "id": "sniper", "name": "Sniper Elite", "price": 5000,
        "image": "images/case_sniper.png", "emoji": "🎯",
        "description": "AWP, SSG 08, SCAR-20 — nishonchilar uchun maxsus",
        "filter": ["all", "qurollar"], "color": "#B468FF", "badge": "NEW",
    },
    {
        "id": "m4a4", "name": "M4A4 Special", "price": 3500,
        "image": "images/case_m4a4.png", "emoji": "🔥",
        "description": "M4A4 kolleksiyasidagi eng zo'r skinlar",
        "filter": ["all", "qurollar"], "color": "#FF6B35",
    },
    {
        "id": "ak47", "name": "AK-47 Series", "price": 4000,
        "image": "images/case_ak47.png", "emoji": "💥",
        "description": "AK-47 ning eng rare skinlari — Wild Lotus, Neon Rider va boshqalar",
        "filter": ["all", "qurollar"], "color": "#FFD700", "badge": "HOT",
    },
    {
        "id": "free", "name": "Kunlik Bepul", "price": 0,
        "image": "images/case_free.png", "emoji": "🎁",
        "description": "Har kuni bir marta bepul! Qaytib keling",
        "filter": ["all"], "color": "#00E676", "badge": "FREE",
    },
]

PRIZES = {
    "budget": [
        {"name": "CZ75-Auto",        "image": "images/cz75.png",     "value": 5,   "weight": 40, "rarity": "common"},
        {"name": "Tec-9 | Titanium", "image": "images/tec9.png",     "value": 15,  "weight": 30, "rarity": "uncommon"},
        {"name": "MP9 | Wild Lily",  "image": "images/mp9.png",      "value": 50,  "weight": 20, "rarity": "rare"},
        {"name": "AK-47 | Redline",  "image": "images/ak47_red.png", "value": 200, "weight": 8,  "rarity": "epic"},
        {"name": "AWP | Asiimov",    "image": "images/awp_asi.png",  "value": 800, "weight": 2,  "rarity": "legendary"},
    ],
    "eco": [
        {"name": "Glock-18 | Groundwater", "image": "images/glock.png",      "value": 10,  "weight": 35, "rarity": "common"},
        {"name": "P250 | Electric Hive",   "image": "images/p250.png",       "value": 30,  "weight": 28, "rarity": "uncommon"},
        {"name": "Five-SeveN | Fowl Play", "image": "images/fiveseven.png",  "value": 80,  "weight": 20, "rarity": "rare"},
        {"name": "Desert Eagle | Kumicho", "image": "images/deagle.png",     "value": 300, "weight": 12, "rarity": "epic"},
        {"name": "Glock | Fade",           "image": "images/glock_fade.png", "value": 800, "weight": 5,  "rarity": "legendary"},
    ],
    "sniper": [
        {"name": "SSG 08 | Abyss",    "image": "images/ssg08.png",  "value": 50,   "weight": 35, "rarity": "uncommon"},
        {"name": "SCAR-20 | Dusk",    "image": "images/scar20.png", "value": 120,  "weight": 28, "rarity": "rare"},
        {"name": "AWP | Hyper Beast", "image": "images/awp_hb.png", "value": 400,  "weight": 15, "rarity": "epic"},
        {"name": "AWP | Dragon Lore", "image": "images/awp_dl.png", "value": 2000, "weight": 3,  "rarity": "legendary"},
    ],
    "m4a4": [
        {"name": "FAMAS | Neural Net",  "image": "images/famas.png",     "value": 40,   "weight": 35, "rarity": "uncommon"},
        {"name": "M4A4 | Eye of Horus", "image": "images/m4a4_eye.png",  "value": 100,  "weight": 30, "rarity": "rare"},
        {"name": "M4A4 | Poseidon",     "image": "images/m4a4_pos.png",  "value": 350,  "weight": 15, "rarity": "epic"},
        {"name": "M4A4 | Howl",         "image": "images/m4a4_howl.png", "value": 3000, "weight": 2,  "rarity": "legendary"},
    ],
    "ak47": [
        {"name": "AK-47 | Cartel",     "image": "images/ak47_cartel.png", "value": 30,   "weight": 35, "rarity": "uncommon"},
        {"name": "AK-47 | Bloodsport", "image": "images/ak47_blood.png",  "value": 90,   "weight": 28, "rarity": "rare"},
        {"name": "AK-47 | Neon Rider", "image": "images/ak47_neon.png",   "value": 350,  "weight": 12, "rarity": "epic"},
        {"name": "AK-47 | Wild Lotus", "image": "images/ak47_lotus.png",  "value": 2500, "weight": 2,  "rarity": "legendary"},
    ],
    "free": [
        {"name": "CZ75-Auto",         "image": "images/cz75.png",     "value": 5,   "weight": 45, "rarity": "common"},
        {"name": "Tec-9 | Titanium",  "image": "images/tec9.png",     "value": 15,  "weight": 30, "rarity": "uncommon"},
        {"name": "MP9 | Wild Lily",   "image": "images/mp9.png",      "value": 50,  "weight": 18, "rarity": "rare"},
        {"name": "AK-47 | Redline",   "image": "images/ak47_red.png", "value": 200, "weight": 6,  "rarity": "epic"},
        {"name": "AWP | Hyper Beast", "image": "images/awp_hb.png",   "value": 400, "weight": 1,  "rarity": "legendary"},
    ],
}

# Stars bilan balansni to'ldirish paketlari.
# "stars" — Telegram'da to'lanadigan miqdor, "bonus" — ustiga qo'shib beriladigan.
PACKAGES = {
    "small":  {"stars": 250,  "bonus": 0,   "label": "250 Stars"},
    "medium": {"stars": 1000, "bonus": 50,  "label": "1000 Stars + 50 bonus"},
    "large":  {"stars": 5000, "bonus": 500, "label": "5000 Stars + 500 bonus"},
}


def get_case(case_id: str) -> dict | None:
    return next((c for c in CASES if c["id"] == case_id), None)


def pick_prize(case_id: str) -> dict:
    pool = PRIZES[case_id]
    prize = _rng.choices(pool, weights=[p["weight"] for p in pool], k=1)[0]
    return dict(prize)  # nusxa — asl ro'yxat o'zgarib ketmasin


def case_stats() -> list[dict]:
    """Har bir case uchun o'rtacha yutuq qiymati va RTP (sotish narxida)."""
    from app.config import SELL_RATE_PERCENT
    out = []
    for case in CASES:
        pool = PRIZES[case["id"]]
        total_w = sum(p["weight"] for p in pool)
        ev = sum(p["value"] * p["weight"] for p in pool) / total_w
        sell_ev = ev * SELL_RATE_PERCENT / 100
        rtp = (sell_ev / case["price"] * 100) if case["price"] else None
        out.append({"id": case["id"], "price": case["price"],
                    "avg_value": round(ev, 1), "avg_sell": round(sell_ev, 1),
                    "rtp_percent": round(rtp, 1) if rtp is not None else None})
    return out


def validate() -> None:
    """Ishga tushishda konfiguratsiya xatolarini darhol ko'rsatadi."""
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "CASES ichida takroriy id bor"
    for cid in ids:
        assert cid in PRIZES and PRIZES[cid], f"'{cid}' case uchun PRIZES yo'q"
        for p in PRIZES[cid]:
            assert p["weight"] > 0 and p["value"] >= 0, f"'{cid}': noto'g'ri weight/value"
    for key, pkg in PACKAGES.items():
        assert pkg["stars"] >= 1, f"Paket '{key}': stars >= 1 bo'lishi kerak"
