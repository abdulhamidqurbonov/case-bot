# CaseVault 🔥

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

## Rasm va ovoz qo'shish (bot orqali)
Botga admin akkauntdan fayl yuboring, izohiga kalitni yozing. `/skins` — barcha kalitlar va nimasi borligi.
- **Qurollar:** `awp_asi`, `ak47_red` … (yoki to'liq nomi `AWP | Asiimov`)
- **Case'lar:** `case_free`, `case_ak`, `case_knife` …
- **O'yinlar:** `game_upgrade`, `game_contract`, `game_crash`, `game_dice` — o'yin kartasida va o'yin sahifasi tepasida chiqadi
- **Ovozlar (MP3/OGG, 2 MB gacha):** `snd_tick`, `snd_spin`, `snd_drop`, `snd_win`, `snd_rare`, `snd_unlock`, `snd_ambient`, `snd_click`, `snd_lose`
Rasm avtomatik moslanadi: chetdagi bo'sh/bir xil fon kesiladi, 640 px gacha kichraytiriladi, WebP'ga o'giriladi.
Ovoz yuklanmagan bo'lsa — ilova o'zining standart ovozini chaladi.

## Admin buyruqlari
`/admin` · `/myid` · `/stats` · `/withdraw_on` · `/withdraw_off` · `/pending` · `/confirm_123` · `/reject_123 sabab` · `/skins` · `/delimg kalit`

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

## Server uxlab qolmasligi uchun (Render bepul tarif)
Bepul tarifda server 15 daqiqa ishlatilmasa uxlaydi va keyingi kirishda Render'ning
"Application loading" sahifasi 30–60 soniya ko'rinadi. Buni oldini olish:
1. https://uptimerobot.com → Add New Monitor → HTTP(s)
2. URL: `https://<servis>.onrender.com/health`, interval: 5 daqiqa
Bitta servis uchun oylik bepul 750 soat yetadi (24/7 ≈ 744 soat).

## Steam'ga chiqarish qoidalari
- Boshida YOPIQ (`WITHDRAW_ENABLED=0`). Ilovada «tez orada ochiladi» deb ochiq yoziladi.
- Ochish/yopish: botda `/withdraw_on` va `/withdraw_off` (deploy kerak emas).
- O'yinchi jami kamida `WITHDRAW_MIN_DEPOSIT` (500) Stars to'lagan bo'lishi kerak; profilda progress ko'rinadi.
- `/stats` — tushgan Stars (≈ $), inventarlardagi skinlar qiymati, kutilayotgan so'rovlar.
- Reja: birinchi 10–20 to'lovdan keyin DMarket'dan skinlar olinadi, shundan so'ng `/withdraw_on`.

## Crash (jonli, hamma uchun bitta raund)
Server raundlarni to'xtovsiz aylantiradi: stavka (10 s, ekranda katta sanoq) → samolyot uchadi → «uchib ketdi» (3 s) → yangi raund.
Hamma bir xil samolyotni va bir-birining stavkalarini ko'radi. Uchish paytida bosilsa — keyingi raundga navbat.
* Crash nuqtasi bazada yashirin, natijani server hisoblaydi (baza soati bo'yicha).
* Holat long-poll orqali darhol keladi (`/api/crash/live`).
* Hech kim ko'rmayotgan bo'lsa sikl pauza qiladi (45 s).
* Server qayta ishga tushsa, tugallanmagan raund stavkalari qaytariladi.
* Bitta stavkadan yutuq `MAX_WIN` dan oshmaydi (kerak bo'lsa avto-yechish majburan qo'yiladi).
Samolyot rasmi: botga `crash_plane` (fonsiz PNG, burni o'ngga). Ovozlar: `snd_fly`, `snd_crash`, `snd_cashout`.

### Koeffitsiyent taqsimoti (CRASH_RTP_PERCENT=93, eng yuqori 100x)
2x dan yuqori: ~46% · 5x+: ~19% · 10x+: ~9% · 20x+: ~5% · 50x+: ~2% · 100x: ~1% · darhol 1.00x: ~7%
Crash xabari bazaga yozishni kutmasdan darhol yuboriladi (Supabase sekin bo'lsa ham ekran ortiqcha ko'tarilmaydi).

## Case qo'shish (bot orqali, kod va deploy kerak emas)
1. Botga `/newcase` yozing.
2. Case rasmini yuboring → nomini yozing → e'lon matnini (title) yozing (yoki `/skip`).
3. Skinlarni yozing, har qatorga `kalit og'irlik`:
   ```
   glock 4000
   deagle 1500
   awp_asi 300
   karambit 5
   ```
4. Bot e'lonni aynan o'yinchilar ko'radigandek ko'rsatadi + narx, RTP, har skin ehtimoli.
   **✅ Qo'shish** yoki **📢 Qo'shish va hammaga yuborish**.
- Narx avtomatik (RTP 90%). Yangi case ro'yxatda bepul case'dan keyin birinchi chiqadi.
- E'londagi «🎁 Case ochish» tugmasi ilovada to'g'ridan-to'g'ri shu case'ni ochadi.
- `/cases` ro'yxat · `/delcase ID` o'chirish/yashirish · `/showcase ID` qaytarish · `/announce ID` e'lonni qayta yuborish
- `/addskin usp_kill | USP-S | Kill Confirmed | covert | 1500` — yangi skin turi
- `/broadcast` — istalgan xabarga reply qilib yozing: hammaga «🎮 Ochish» tugmasi bilan ketadi

## Xavfsizlik (Supabase RLS)
Server ishga tushganda barcha jadvallarda RLS yoqiladi va `anon`/`authenticated` rollardan huquqlar olinadi —
Supabase'ning ochiq REST API'si orqali hech kim ma'lumot o'qiy/o'zgartira olmaydi. Bot jadvallar egasi sifatida ulanadi.
`SUPABASE_URL` va `SUPABASE_KEY` kodda ishlatilmaydi — Render'dan o'chirib tashlash mumkin.

## AI biznes hamkor (Groq)

1. https://console.groq.com → API Keys → Create API Key (bepul tarif bor).
2. Render → Environment → `GROQ_API_KEY` = kalit. Ixtiyoriy: `AI_MODEL` (standart `openai/gpt-oss-120b`),
   `AI_FALLBACK_MODEL` (limit tugasa — `llama-3.3-70b-versatile`), `SUPPORT_AI=0` — o'yinchilar supportini o'chirish,
   `SUPPORT_DAILY_LIMIT` — bitta o'yinchi kuniga nechta savol bera oladi (standart 30).
   Model nomi o'zgargan bo'lsa, bot hisobdagi mos modelni o'zi tanlaydi.
3. Botda: `/ai` — suhbat rejimi (statistika, «@username nima qilyapti», xatolar, g'oyalar, reja), `/ai savol`,
   `/ai_off`, `/ai_reset`, `/ai_daily` — har kuni 21:00 (Toshkent) hisobot.

AI faqat ma'lumot o'qiydi — balans, skin yoki sozlamani o'zgartira olmaydi. O'yinchilar uchun support ilovadagi
Profil → «Yordam» va botga yozilgan oddiy xabarlar orqali ishlaydi; hal qila olmasa muammoni adminga yuboradi.

## Render «Application loading» sahifasi chiqmasligi uchun

* Eng oddiy: https://cron-job.org da `https://SIZNING-SERVIS.onrender.com/health` ga har 5 daqiqada so'rov.
* To'liq yechim: ilova sahifasini Cloudflare Pages'ga qo'yish (bepul, uxlamaydi). Cloudflare → Workers & Pages →
  Create → Pages → GitHub repo'ni ulash → Build command bo'sh, Build output directory: `case-bot/public` → Deploy.
  So'ng Render'da `FRONTEND_URL` = olingan manzil (masalan `https://case-vault.pages.dev`). Bot tugmalari va menyu
  tugmasi o'sha sahifani ochadi; server uxlagan bo'lsa ham darhol CaseVault seyf ekrani chiqadi.
