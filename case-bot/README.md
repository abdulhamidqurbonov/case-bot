# CS2 Cases Bot 🔥

Telegram Mini App: CS2 case'lar, Upgrade, Shartnoma, Crash, Dice. To'lov — Telegram Stars.
Python 3.11 · FastAPI · python-telegram-bot 20 · PostgreSQL (Supabase) · Render.

## Tuzilma
```
case-bot/
├── main.py           server + webhook
├── app/
│   ├── config.py     sozlamalar (env)
│   ├── catalog.py    skinlar, case'lar, paketlar  ← narx/skinlarni shu yerda o'zgartirasiz
│   ├── games.py      o'yin mantiqi (Upgrade, Shartnoma, Crash, Dice)
│   ├── database.py   baza (atomik amallar, balance_log)
│   ├── api.py        WebApp API
│   ├── images.py     /img/<kalit> — skin rasmlari
│   └── bot.py        bot, to'lovlar, admin buyruqlari
└── public/
    ├── index.html    WebApp
    └── images/       (ixtiyoriy) <kalit>.png rasmlar
```

## Render
- Root Directory: `case-bot` · Build: `pip install -r requirements.txt` · Start: `python main.py`
- Environment: `.env.example` ga qarang. Majburiy: `BOT_TOKEN`, `DATABASE_URL`, `WEBAPP_URL`.

## Haqiqiy qurol rasmlarini qo'shish
1. Botga (ADMIN_CHAT_ID akkauntidan) rasm yuboring.
2. Rasm izohiga skin kalitini yozing: `awp_asi` (yoki to'liq nomi: `AWP | Asiimov`).
3. Fonsiz PNG bo'lsa — **fayl sifatida** yuboring, aks holda Telegram fonni oq qiladi.
- Case rasmi uchun kalit: `case_ak`, `case_knife`, `case_free` …
- `/skins` — qaysi skinda rasm bor/yo'qligini ko'rsatadi. `/delimg kalit` — o'chiradi.
Rasmlar bazada saqlanadi, shuning uchun Render qayta ishga tushsa ham yo'qolmaydi.

## Admin buyruqlari
`/admin` · `/pending` · `/confirm_123` · `/reject_123 sabab` · `/skins` · `/delimg kalit`

## Iqtisod
- Skin qiymati (`catalog.py` → `SKINS`) Stars'da. Sotilsa shuncha Stars qaytadi.
- Case narxi avtomatik: o'rtacha yutuq ÷ `CASE_RTP_PERCENT`. Faqat skin qiymati va og'irligini o'zgartiring.
- O'yinlar RTP'si env orqali sozlanadi. Server ishga tushganda har bir case narxi va RTP logga chiqadi.
- Steam'ga chiqarish: minimal qiymat `MIN_WITHDRAW_VALUE`, kamida bitta to'lov talab qilinadi.

## Yangi case qo'shish
`catalog.py` → `CASES` ga qo'shing:
```python
{"id": "awp", "name": "AWP", "badge": "Yangi", "items": [("awp_hb", 500), ("awp_asi", 200), ("awp_dl", 2)]},
```
