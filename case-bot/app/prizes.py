import random

# ─────────────────────────────────────────────────────────────────────
#  KEYSLAR SOZLAMALARI
#  image: "images/fayl_nomi.png"  —  public/images/ papkasiga soling
# ─────────────────────────────────────────────────────────────────────

CASES = [
    {
        "id":          "budget",
        "name":        "Budget",
        "price":       750,        # Stars narxi
        "image":       "images/case_budget.png",
        "emoji":       "🔫",
        "description": "Kichik xavf, katta potensial — yangi boshlovchilar uchun",
        "filter":      ["all", "tematik", "budget"],
        "color":       "#00E676",
    },
    {
        "id":          "eco",
        "name":        "Eco",
        "price":       2500,
        "image":       "images/case_eco.png",
        "emoji":       "⚡",
        "description": "Eco roundlari uchun — past narxda yuqori qiymatli qurollar",
        "filter":      ["all", "tematik"],
        "color":       "#4DC8FF",
    },
    {
        "id":          "sniper",
        "name":        "Sniper Elite",
        "price":       5000,
        "image":       "images/case_sniper.png",
        "emoji":       "🎯",
        "description": "AWP, SSG 08, SCAR-20 — nishonchilar uchun maxsus",
        "filter":      ["all", "qurollar"],
        "color":       "#B468FF",
        "badge":       "NEW",
    },
    {
        "id":          "m4a4",
        "name":        "M4A4 Special",
        "price":       3500,
        "image":       "images/case_m4a4.png",
        "emoji":       "🔥",
        "description": "M4A4 kolleksiyasidagi eng zo'r skinlar",
        "filter":      ["all", "qurollar"],
        "color":       "#FF6B35",
    },
    {
        "id":          "ak47",
        "name":        "AK-47 Series",
        "price":       4000,
        "image":       "images/case_ak47.png",
        "emoji":       "💥",
        "description": "AK-47 ning eng rare skinlari — Wild Lotus, Asiimov va boshqalar",
        "filter":      ["all", "qurollar"],
        "color":       "#FFD700",
        "badge":       "HOT",
    },
    {
        "id":          "free",
        "name":        "Kunlik Bepul",
        "price":       0,
        "image":       "images/case_free.png",
        "emoji":       "🎁",
        "description": "Har kuni bir marta bepul! Qaytib keling",
        "filter":      ["all"],
        "color":       "#00E676",
        "badge":       "FREE",
    },
]

# ── Sovg'alar ────────────────────────────────────────────────────────
#  Har bir item uchun image — public/images/ ga shu nomda fayl soling

PRIZES = {
    "budget": [
        {"name": "CZ75-Auto",         "image": "images/cz75.png",       "value": 5,   "weight": 40, "rarity": "common"},
        {"name": "Tec-9 | Titanium",  "image": "images/tec9.png",       "value": 15,  "weight": 30, "rarity": "uncommon"},
        {"name": "MP9 | Wild Lily",   "image": "images/mp9.png",        "value": 50,  "weight": 20, "rarity": "rare"},
        {"name": "AK-47 | Redline",   "image": "images/ak47_red.png",   "value": 200, "weight": 8,  "rarity": "epic"},
        {"name": "AWP | Asiimov",     "image": "images/awp_asi.png",    "value": 800, "weight": 2,  "rarity": "legendary"},
    ],
    "eco": [
        {"name": "Glock-18 | Groundwater", "image": "images/glock.png",      "value": 10,  "weight": 35, "rarity": "common"},
        {"name": "P250 | Electric Hive",   "image": "images/p250.png",       "value": 30,  "weight": 28, "rarity": "uncommon"},
        {"name": "Five-SeveN | Fowl Play", "image": "images/fiveseven.png",  "value": 80,  "weight": 20, "rarity": "rare"},
        {"name": "Desert Eagle | Kumicho", "image": "images/deagle.png",     "value": 300, "weight": 12, "rarity": "epic"},
        {"name": "Glock | Fade",           "image": "images/glock_fade.png", "value": 800, "weight": 5,  "rarity": "legendary"},
    ],
    "sniper": [
        {"name": "SSG 08 | Abyss",     "image": "images/ssg08.png",    "value": 50,   "weight": 35, "rarity": "uncommon"},
        {"name": "SCAR-20 | Dusk",     "image": "images/scar20.png",   "value": 120,  "weight": 28, "rarity": "rare"},
        {"name": "AWP | Hyper Beast",  "image": "images/awp_hb.png",   "value": 400,  "weight": 15, "rarity": "epic"},
        {"name": "AWP | Dragon Lore",  "image": "images/awp_dl.png",   "value": 2000, "weight": 3,  "rarity": "legendary"},
    ],
    "m4a4": [
        {"name": "FAMAS | Neural Net",    "image": "images/famas.png",       "value": 40,   "weight": 35, "rarity": "uncommon"},
        {"name": "M4A4 | Eye of Horus",   "image": "images/m4a4_eye.png",    "value": 100,  "weight": 30, "rarity": "rare"},
        {"name": "M4A4 | Poseidon",       "image": "images/m4a4_pos.png",    "value": 350,  "weight": 15, "rarity": "epic"},
        {"name": "M4A4 | Howl",           "image": "images/m4a4_howl.png",   "value": 3000, "weight": 2,  "rarity": "legendary"},
    ],
    "ak47": [
        {"name": "AK-47 | Cartel",      "image": "images/ak47_cartel.png", "value": 30,   "weight": 35, "rarity": "uncommon"},
        {"name": "AK-47 | Bloodsport",  "image": "images/ak47_blood.png",  "value": 90,   "weight": 28, "rarity": "rare"},
        {"name": "AK-47 | Neon Rider",  "image": "images/ak47_neon.png",   "value": 350,  "weight": 12, "rarity": "epic"},
        {"name": "AK-47 | Wild Lotus",  "image": "images/ak47_lotus.png",  "value": 2500, "weight": 2,  "rarity": "legendary"},
    ],
    "free": [
        {"name": "CZ75-Auto",           "image": "images/cz75.png",        "value": 5,   "weight": 45, "rarity": "common"},
        {"name": "Tec-9 | Titanium",    "image": "images/tec9.png",        "value": 15,  "weight": 30, "rarity": "uncommon"},
        {"name": "MP9 | Wild Lily",     "image": "images/mp9.png",         "value": 50,  "weight": 18, "rarity": "rare"},
        {"name": "AK-47 | Redline",     "image": "images/ak47_red.png",    "value": 200, "weight": 6,  "rarity": "epic"},
        {"name": "AWP | Hyper Beast",   "image": "images/awp_hb.png",      "value": 400, "weight": 1,  "rarity": "legendary"},
    ],
}

PACKAGES = {
    "small":  {"stars": 50,  "cases": 3,  "label": "3 ta Premium Case"},
    "medium": {"stars": 150, "cases": 10, "label": "10 ta Premium Case"},
    "large":  {"stars": 500, "cases": 40, "label": "40 ta Premium Case"},
}


def pick_prize(case_id: str) -> dict:
    pool  = PRIZES.get(case_id, PRIZES["free"])
    total = sum(p["weight"] for p in pool)
    rand  = random.uniform(0, total)
    for prize in pool:
        if rand < prize["weight"]:
            return prize
        rand -= prize["weight"]
    return pool[0]


def get_case(case_id: str) -> dict | None:
    return next((c for c in CASES if c["id"] == case_id), None)
