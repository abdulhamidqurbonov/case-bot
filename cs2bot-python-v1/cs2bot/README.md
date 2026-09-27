# CS2 Cases Bot 🔫

Python + FastAPI + Supabase + Railway

## Tuzilma
```
cs2bot/
├── main.py                 ← Ishga tushirish
├── requirements.txt
├── .env.example            ← .env yasang
├── supabase_schema.sql     ← Supabase da ishga tushiring
├── app/
│   ├── config.py           ← Sozlamalar
│   ├── database.py         ← Supabase so'rovlar
│   ├── prizes.py           ← Case va sovg'alar ro'yxati
│   ├── api.py              ← FastAPI endpointlar
│   └── bot.py              ← Telegram bot
└── public/
    ├── index.html          ← WebApp (bir fayl)
    └── images/             ← RASMLAR SHU YERGA
```

## 1. Supabase sozlash
1. supabase.com → yangi project
2. SQL Editor → supabase_schema.sql ni copy-paste
3. Settings → API → URL va anon key ni oling

## 2. .env fayl
```
BOT_TOKEN=...
WEBAPP_URL=https://sizning-url.up.railway.app
ADMIN_CHAT_ID=sizning_telegram_id
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
CHANNEL_USERNAME=@kanalingiz   # ixtiyoriy
BOT_USERNAME=botismi           # /start ref uchun
```

## 3. Railway deploy
1. railway.app → New Project → GitHub repo
2. Environment Variables → .env dagi barcha qiymatlar
3. Deploy → URL oling → WEBAPP_URL ga yozing

## 4. UptimeRobot (uyg'otib turish)
1. uptimerobot.com → Add Monitor
2. HTTP(s) → URL: https://sizning-url.up.railway.app
3. Interval: 5 daqiqa

## 5. Qurol rasmlari qo'shish 🔫

`public/images/` papkasiga shu nomda rasmlar qo'ying:

### Case rasmlari (asosiy karta):
| Fayl | Qaysi case |
|------|-----------|
| case_budget.png | Budget case |
| case_eco.png | Eco case |
| case_sniper.png | Sniper Elite |
| case_m4a4.png | M4A4 Special |
| case_ak47.png | AK-47 Series |
| case_free.png | Kunlik Bepul |

### Item rasmlari (yutib olinadigan skinlar):
| Fayl | Skin |
|------|------|
| cz75.png | CZ75-Auto |
| tec9.png | Tec-9 |
| mp9.png | MP9 Wild Lily |
| ak47_red.png | AK-47 Redline |
| awp_asi.png | AWP Asiimov |
| glock.png | Glock-18 |
| p250.png | P250 |
| fiveseven.png | Five-SeveN |
| deagle.png | Desert Eagle |
| glock_fade.png | Glock Fade |
| ssg08.png | SSG 08 |
| scar20.png | SCAR-20 |
| awp_hb.png | AWP Hyper Beast |
| awp_dl.png | AWP Dragon Lore |
| famas.png | FAMAS |
| m4a4_eye.png | M4A4 Eye of Horus |
| m4a4_pos.png | M4A4 Poseidon |
| m4a4_howl.png | M4A4 Howl |
| ak47_cartel.png | AK-47 Cartel |
| ak47_blood.png | AK-47 Bloodsport |
| ak47_neon.png | AK-47 Neon Rider |
| ak47_lotus.png | AK-47 Wild Lotus |

### Ticker rasmlari (bosh sahifa):
| Fayl | Ko'rsatiladi |
|------|-------------|
| aug.png | AUG ticker |

**Rasm manbalar:**
- Steam Market → qurol sahifasi → rasm saqlash
- https://wiki.cs.money/skins — PNG formatda
- CS2 o'yinidan screenshot

**Rasm kelmasa** → avtomatik emoji ko'rsatiladi ✅

## 6. Admin buyruqlari
Bot orqali:
- `/confirm_123` — withdraw so'rov #123 ni tasdiqlash (Steam ga yuborgandan keyin)

## 7. Yangi case qo'shish
`app/prizes.py` da `CASES` listiga qo'shing:
```python
{
    "id": "yangi",
    "name": "Yangi Case",
    "price": 1000,
    "image": "images/case_yangi.png",
    "emoji": "🔫",
    "description": "Tavsif...",
    "filter": ["all", "qurollar"],
    "color": "#00E676",
}
```
`PRIZES` dictiga ham qo'shing.

## 8. Lokalda sinash
```bash
pip install -r requirements.txt
cp .env.example .env
# .env ni to'ldiring
python main.py
```
