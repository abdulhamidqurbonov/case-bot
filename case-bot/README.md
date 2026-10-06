# CS2 Cases Bot 🔫

Python + FastAPI + python-telegram-bot + PostgreSQL (Supabase) · Render'da ishlaydi.

## Tuzilma
```
case-bot/
├── main.py              ← server + webhook
├── app/
│   ├── config.py        ← barcha sozlamalar (env)
│   ├── database.py      ← baza: atomik amallar, balance_log
│   ├── prizes.py        ← case'lar, sovg'alar, Stars paketlari
│   ├── api.py           ← WebApp API
│   └── bot.py           ← bot buyruqlari, to'lovlar, admin
└── public/
    ├── index.html       ← WebApp
    └── images/          ← rasmlar
```

## Render sozlamalari
- Root Directory: `case-bot`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Environment: `.env.example` dagi o'zgaruvchilar (majburiylari: `BOT_TOKEN`, `DATABASE_URL`, `WEBAPP_URL`)

`DATABASE_URL` — Supabase → Connect → **Session pooler** dagi stringni aynan nusxalang.

## Admin buyruqlari (botda, ADMIN_CHAT_ID dan)
- `/pending` — kutilayotgan Steam so'rovlari
- `/confirm_123` — skin yuborildi deb tasdiqlash
- `/reject_123 sabab` — rad etish (skin foydalanuvchiga qaytadi)

## Pul tizimi
- Foydalanuvchi Stars to'laydi → balansga Stars tushadi (`PACKAGES` da bonus ham bor).
- Case narxi balansdan atomik yechiladi; balans hech qachon minusga tushmaydi.
- Har bir o'zgarish `balance_log` jadvaliga yoziladi.
- Server ishga tushganda har bir case'ning RTP (o'rtacha qaytim %) logga chiqadi.

## Yangi o'yin qo'shish
O'yin natijasini hisoblang va balansni shunday o'zgartiring:
```python
from app.database import change_balance, GameError
change_balance(user_id, -stavka, "crash_bet", game_id)   # yetmasa GameError("insufficient_stars")
change_balance(user_id, +yutuq, "crash_win", game_id)
```

## Lokal ishga tushirish
```bash
pip install -r requirements.txt
cp .env.example .env   # to'ldiring
python main.py
```
