# Case Opening Bot (Telegram Mini App + Stars)

Telegram case-opening bot: bir nechta nomli keyslar (Bepul, Byudjet, Mashhur, Yulduzli, VIP, Jackpot), har birining o'z narxi va sovg'a to'plami bor. Diamond — faqat Telegram Stars orqali sotib olinadigan virtual valyuta.

## Tuzilma

```
case-bot/
  server/
    index.js      # Express API + Telegraf bot
    db.js         # SQLite (better-sqlite3)
    cases.js      # Keyslar katalogi, kategoriyalar va RNG (weighted random)
  public/
    index.html    # Mini App: keyslar katalogi, case detail, reel animatsiyasi, do'kon
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
- **Keyslar katalogi**: `server/cases.js` da har bir keys — nomi, narxi (diamond), kategoriyasi, tagline va o'z sovg'a to'plami bilan tavsiflanadi. `/api/cases` orqali frontendga statik ro'yxat + top-3 preview sovg'a beriladi
- **Bepul keys**: kuniga 1 marta, `free_cases_left` / `last_free_case_at` orqali kuzatiladi (narxi 0)
- **Pullik keyslar**: diamond bilan ochiladi, bir vaqtda 1–5 tagacha ochish mumkin (`quantity`)
- **Diamond sotib olish**: Stars bilan → `createInvoiceLink` (currency: `XTR`) → foydalanuvchi `openInvoice()` orqali to'laydi → `successful_payment` eventida balansga qo'shiladi. Paketlar `DIAMOND_PACKAGES` da (`server/index.js`), 15 000 dan boshlanadi
- **Sovg'a tanlash**: har bir keys ichida weighted random — og'irligi (weight) qancha katta bo'lsa, ehtimoli shuncha yuqori. Qimmatroq keyslarda qimmatroq sovg'a ehtimoli oshirilgan
- **Xavfsizlik**: har bir so'rovda Telegram `initData` HMAC orqali tekshiriladi (`verifyInitData`) — bu bo'lmasa, xohlagan odam API'ga to'g'ridan-to'g'ri murojaat qilib balansni firibgarlik bilan oshirib yuborishi mumkin

## Rasm qo'shish (siz o'zingiz qilasiz)

Har bir sovg'a va keys "icon" turiga ega: `pistol`, `smg`, `rifle`, `shotgun`, `sniper`, `knife`. Rasm shu yerga qo'yiladi:

```
public/assets/weapons/pistol.png
public/assets/weapons/smg.png
public/assets/weapons/rifle.png
public/assets/weapons/shotgun.png
public/assets/weapons/sniper.png
public/assets/weapons/knife.png
```

Hozircha o'sha papkada oddiy rangli PLACEHOLDER rasmlar bor — shunchaki xuddi shu nomdagi faylni o'z rasmingiz bilan almashtiring (fayl nomini o'zgartirmang). Rasm topilmasa ham ilova sinmaydi — rangli vektor zaxira ko'rinishi avtomatik chiqadi (`public/assets/weapons/README.txt`da tushuntirilgan).

## Tasodifiylik haqida

Qaysi sovg'a tushishi **serverda** (`server/cases.js` → `pickPrize()`) `Math.random()` orqali, "weight" ustuniga qarab hisoblanadi — bu haqiqiy tasodifiy tanlov, frontendda emas, oldindan belgilanmagan. Ekrandagi aylanuvchi "reel" animatsiyasi faqat server allaqachon tanlagan natijani vizual ko'rsatish uchun; pedestal/ramka dizayni har qanday natijani bir xil ko'rsatadi, natijaga ta'sir qilmaydi.



Diamond — faqat Telegram Stars orqali sotib olinadigan, naqd pulga yoki boshqa aktivga almashtirib bo'lmaydigan virtual valyuta (cashout yo'q). Ataylab quyidagilar **qo'shilmagan**:

- Karta/Google Pay/Apple Pay/kripto orqali to'g'ridan-to'g'ri to'lov
- Steam skin'larni valyuta yoki to'lov vositasi sifatida qabul qilish

Bular real pulli, ko'p mamlakatlarda litsenziyasiz gembling hisoblanadigan modelga olib keladi (ayniqsa Steam skin orqali to'lov — Valve tomonidan qattiq taqiqlangan "skin gambling" yo'nalishi). Agar keyinchalik real to'lov usullarini qo'shmoqchi bo'lsangiz, avval mamlakatingizdagi qimor/lotereya litsenziyasi talablarini yurist bilan tekshiring.

## Keyingi qadamlar (tavsiya)

- **Referal mukofoti**: `referred_by` ustuni bor, lekin hozircha mukofot berilmaydi — do'st taklif qilganga bonus diamond qo'shish mumkin
- **Yangi keys qo'shish**: `server/cases.js` dagi `CASES` massiviga yangi obyekt qo'shish yetarli — frontend avtomatik moslashadi
- **Leaderboard**: `case_openings` jadvali orqali eng ko'p yutgan foydalanuvchilar reytingini chiqarish oson
- **Webhook**: hozir `bot.launch()` polling rejimida ishlaydi; production'da webhook'ga o'tkazish tavsiya etiladi (ko'proq trafik uchun)
