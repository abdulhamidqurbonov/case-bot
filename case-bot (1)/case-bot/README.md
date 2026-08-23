# Case Opening Bot (Telegram Mini App + Stars)

Telegram case-opening bot: foydalanuvchilar kuniga 1 marta bepul case ochadi, Telegram Stars orqali premium case sotib olishlari mumkin.

## Tuzilma

```
case-bot/
  server/
    index.js      # Express API + Telegraf bot
    db.js         # SQLite (better-sqlite3)
    prizes.js      # Sovg'alar va RNG (weighted random)
  public/
    index.html     # Mini App (reel animatsiyasi + do'kon)
  .env.example
```

## O'rnatish

1. **Bot yaratish**: Telegram'da [@BotFather](https://t.me/BotFather) ga o'ting, `/newbot` bilan bot yarating, tokenni oling.
2. **Stars yoqish**: BotFather'da `/mybots` → botingiz → Payments → Stars allaqachon yoqilgan bo'ladi (alohida provider kerak emas).
3. **Domenga joylashtiring** (Mini App HTTPS talab qiladi — Render, Railway, VPS + nginx yoki ngrok test uchun).

```bash
cd case-bot
npm install
cp .env.example .env
# .env faylini to'ldiring: BOT_TOKEN va WEBAPP_URL (https bo'lishi shart)
npm start
```

4. **BotFather'da Mini App URL'ni sozlang**: `/mybots` → botingiz → Bot Settings → Menu Button → Mini App URL sifatida `WEBAPP_URL` ni kiriting.

## Qanday ishlaydi

- `/start` — foydalanuvchi bazaga yoziladi, referal kod bo'lsa saqlanadi (`?start=ref_12345`)
- **Bepul case**: kuniga 1 marta, `free_cases_left` / `last_free_case_at` orqali kuzatiladi
- **Premium case**: Stars bilan sotib olinadi → `createInvoiceLink` (currency: `XTR`) → foydalanuvchi `openInvoice()` orqali to'laydi → `successful_payment` eventida balansga qo'shiladi
- **Sovg'a tanlash**: `prizes.js` da weighted random — og'irligi (weight) qancha katta bo'lsa, ehtimoli shuncha yuqori. Premium case'da qimmatroq sovg'alar ehtimoli oshirilgan
- **Xavfsizlik**: har bir so'rovda Telegram `initData` HMAC orqali tekshiriladi (`verifyInitData`) — bu bo'lmasa, xohlagan odam API'ga to'g'ridan-to'g'ri murojaat qilib balansni firibgarlik bilan oshirib yuborishi mumkin

## Keyingi qadamlar (tavsiya)

- **Referal mukofoti**: `referred_by` ustuni bor, lekin hozircha mukofot berilmaydi — do'st taklif qilganga bonus case qo'shish mumkin
- **Withdraw/almashtirish**: hozir sovg'alar faqat "ball" sifatida saqlanadi, haqiqiy NFT/TON bilan bog'lamagan — agar buni qilmoqchi bo'lsangiz, alohida (va ehtiyotkorlik bilan) TON smart-contract integratsiyasi kerak bo'ladi
- **Leaderboard**: `case_openings` jadvali orqali eng ko'p yutgan foydalanuvchilar reytingini chiqarish oson
- **Webhook**: hozir `bot.launch()` polling rejimida ishlaydi; production'da webhook'ga o'tkazish tavsiya etiladi (ko'proq trafik uchun)
