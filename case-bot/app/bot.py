"""Telegram bot: /start (referal), /me, /setsteam, Stars to'lovlari va admin buyruqlari."""
import asyncio
import json
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    PreCheckoutQueryHandler, filters,
)

from app import database as dbm
from app.config import ADMIN_CHAT_ID, BOT_TOKEN, REFERRAL_BONUS_STARS, WEBAPP_URL
from app.catalog import CASE_LIST, PACKAGES, SKINS, key_by_name

logger = logging.getLogger(__name__)

_app: Application | None = None


def _esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _play_kb(text: str = "🎮 O'yinni boshlash") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, web_app=WebAppInfo(url=WEBAPP_URL))]])


def _is_admin(update: Update) -> bool:
    if not ADMIN_CHAT_ID:
        return False
    user = update.effective_user
    chat = update.effective_chat
    return (user and user.id == ADMIN_CHAT_ID) or (chat and chat.id == ADMIN_CHAT_ID)


# ── Foydalanuvchi buyruqlari ──────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    _, created = await asyncio.to_thread(
        dbm.get_or_create_user, user.id, user.username, user.first_name)

    # Referal faqat birinchi marta kirgan foydalanuvchi uchun hisoblanadi
    if created and ctx.args and ctx.args[0].startswith("ref_"):
        try:
            ref_id = int(ctx.args[0][4:])
        except ValueError:
            ref_id = None
        if ref_id and await asyncio.to_thread(
                dbm.register_referral, ref_id, user.id, REFERRAL_BONUS_STARS):
            try:
                await ctx.bot.send_message(
                    ref_id, f"🎉 Yangi referal! +{REFERRAL_BONUS_STARS} Stars balansingizga qo'shildi.")
            except Exception:
                pass

    name = _esc(user.first_name or "do'stim")
    await update.message.reply_text(
        f"<b>CaseVault</b>'ga xush kelibsiz, {name}! 🔥\n\n"
        "Case oching, Upgrade, Crash va boshqa o'yinlarda skin yutib oling.\n"
        "Har kuni bitta bepul case sizni kutadi 🎁",
        reply_markup=_play_kb(),
        parse_mode="HTML",
    )


async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u, _ = await asyncio.to_thread(dbm.get_or_create_user, user.id, user.username, user.first_name)
    steam = "✅ qo'shilgan" if u.get("steam_trade_url") else "❌ yo'q — /setsteam bilan qo'shing"
    await update.message.reply_text(
        f"<b>Profilingiz</b>\n\n⭐ Balans: <b>{u['stars_balance']}</b> Stars\n🔗 Steam: {steam}",
        parse_mode="HTML",
    )


async def cmd_setsteam(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app import steam

    if not ctx.args:
        await update.message.reply_text(
            "<b>Steam Trade URL qo'shish</b>\n\n"
            "Eng osoni — ilovadagi Profil bo'limida «Qayerdan topaman?» qo'llanmasi.\n\n"
            "Yoki shu yerga yozing:\n<code>/setsteam https://steamcommunity.com/tradeoffer/new/?partner=...&amp;token=...</code>",
            parse_mode="HTML",
        )
        return
    try:
        clean, partner, _ = steam.parse_trade_url(ctx.args[0])
        id64 = steam.to_id64(partner)
        prof = await steam.fetch_profile(id64)
    except steam.SteamError as e:
        await update.message.reply_text(
            "❌ Bunday Steam akkaunt topilmadi." if e.code == "steam_not_found"
            else "❌ Noto'g'ri URL. To'liq Trade URL yuboring (partner va token bilan).")
        return
    await asyncio.to_thread(dbm.set_steam_url, update.effective_user.id, clean, id64,
                            (prof or {}).get("name"), (prof or {}).get("avatar"))
    who = f"\nAkkaunt: <b>{_esc(prof['name'])}</b>" if prof and prof.get("name") else ""
    await update.message.reply_text(f"✅ Steam Trade URL saqlandi!{who}", parse_mode="HTML")


# ── To'lovlar (Telegram Stars) ────────────────────────────────────────

def _parse_payload(payload: str) -> tuple[int | None, dict | None, str | None]:
    try:
        data = json.loads(payload)
        key = data.get("p")
        return int(data.get("u")), PACKAGES.get(key), key
    except (ValueError, TypeError, AttributeError):
        return None, None, None


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    uid, pkg, _ = _parse_payload(q.invoice_payload)
    if (pkg is None or uid != q.from_user.id
            or q.currency != "XTR" or q.total_amount != pkg["stars"]):
        await q.answer(ok=False, error_message="Paket topilmadi. Do'kondan qaytadan urinib ko'ring.")
        return
    await q.answer(ok=True)


async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pay = update.message.successful_payment
    user = update.effective_user
    _, pkg, key = _parse_payload(pay.invoice_payload)
    if pkg is None:
        logger.error("Noma'lum paket bilan to'lov: %s (user %s)", pay.invoice_payload, user.id)
        return

    credit = pay.total_amount + pkg["bonus"]
    balance = await asyncio.to_thread(
        dbm.save_payment, user.id, pay.total_amount, credit,
        pay.telegram_payment_charge_id, key, user.username, user.first_name)
    if balance is None:
        return  # bu to'lov allaqachon qayd etilgan

    await update.message.reply_text(
        f"✅ <b>To'lov qabul qilindi!</b>\n\n+{credit} Stars balansingizga qo'shildi.\n"
        f"Joriy balans: <b>{balance}</b> Stars",
        parse_mode="HTML",
        reply_markup=_play_kb("🎮 Case ochish"),
    )


# ── Admin buyruqlari ──────────────────────────────────────────────────

_ADMIN_RE = re.compile(r"^/(confirm|reject)_(\d+)(?:@\w+)?(?:\s+(.*))?$", re.S)


async def cmd_admin_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    m = _ADMIN_RE.match(update.message.text or "")
    if not m:
        return
    action, req_id, note = m.group(1), int(m.group(2)), (m.group(3) or "").strip()

    if action == "confirm":
        req = await asyncio.to_thread(dbm.confirm_withdraw, req_id)
        user_text = f"✅ <b>Skin yuborildi!</b>\n\n{_esc(req['prize_name'])} Steam'ga yuborildi. Trade offerlaringizni tekshiring." if req else ""
    else:
        req = await asyncio.to_thread(dbm.reject_withdraw, req_id, note)
        user_text = (f"❌ <b>Chiqarish so'rovi rad etildi</b>\n\n{_esc(req['prize_name'])} inventaringizga qaytarildi."
                     + (f"\nSabab: {_esc(note)}" if note else "")) if req else ""

    if not req:
        await update.message.reply_text(f"#{req_id} topilmadi yoki allaqachon ko'rib chiqilgan.")
        return
    try:
        await ctx.bot.send_message(req["telegram_id"], user_text, parse_mode="HTML")
    except Exception:
        logger.warning("Foydalanuvchiga xabar yuborilmadi: %s", req["telegram_id"])
    await update.message.reply_text(
        ("✅ Tasdiqlandi" if action == "confirm" else "↩️ Rad etildi, skin qaytarildi") + f" — #{req_id}")


async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    rows = await asyncio.to_thread(dbm.list_pending_withdrawals)
    if not rows:
        await update.message.reply_text("Kutilayotgan so'rovlar yo'q ✅")
        return
    lines = []
    for r in rows:
        who = "@" + r["username"] if r.get("username") else f"id {r['telegram_id']}"
        lines.append(f"#{r['id']} — {_esc(r['prize_name'])} — {_esc(who)}\n"
                     f"/confirm_{r['id']}  /reject_{r['id']}")
    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Bot xatosi", exc_info=ctx.error)


# ── Media: rasm va ovozlar (admin) ────────────────────────────────────

def _resolve_key(text: str) -> str | None:
    from app import media
    t = (text or "").strip().split()[0].lower() if (text or "").strip() else ""
    if t in media.ALL_KEYS:
        return t
    return key_by_name(text or "")


async def on_admin_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin rasm yoki ovoz yuboradi, izohiga kalitni yozadi."""
    from app import media
    from app.images import forget

    if not _is_admin(update):
        return
    msg = update.message
    is_audio = bool(msg.audio or msg.voice or (msg.document and (msg.document.mime_type or "").startswith("audio/")))
    key = _resolve_key(msg.caption or "")
    if not key:
        hint = "snd_tick" if is_audio else "awp_asi"
        await msg.reply_text(f"Izohga kalitni yozing, masalan: <code>{hint}</code>\nRo'yxat: /skins",
                             parse_mode="HTML")
        return
    if is_audio != (key in media.SOUND_KEYS):
        await msg.reply_text("Bu kalit " + ("ovoz uchun — audio fayl yuboring." if key in media.SOUND_KEYS
                                            else "rasm uchun — rasm yuboring."))
        return

    file_obj = msg.audio or msg.voice or (msg.photo[-1] if msg.photo else None) or msg.document
    limit = media.MAX_SOUND_IN if is_audio else media.MAX_IMAGE_IN
    if file_obj.file_size and file_obj.file_size > limit:
        await msg.reply_text(f"Fayl juda katta. Ko'pi bilan {limit // 1024 // 1024} MB.")
        return
    data = bytes(await (await file_obj.get_file()).download_as_bytearray())

    try:
        if is_audio:
            mime = media.check_sound(data, getattr(file_obj, "mime_type", "") or "")
            info = f"{max(1, len(data) // 1024)} KB"
        else:
            src_kb = len(data) // 1024
            data, mime = await asyncio.to_thread(media.normalize_image, data, key)
            info = f"{src_kb} KB → {len(data) // 1024} KB, avtomatik moslandi"
    except ValueError as e:
        await msg.reply_text({"too_big": "Fayl juda katta.", "not_image": "Bu rasm emas yoki fayl buzilgan.",
                              "not_audio": "Bu ovoz fayli emas. MP3 yoki OGG yuboring."}.get(str(e), "Xato fayl."))
        return

    await asyncio.to_thread(dbm.save_skin_image, key, data, mime)
    forget(key)
    label = (media.SOUNDS.get(key) or (SKINS[key][0] if key in SKINS else key))
    await msg.reply_text(f"✅ Saqlandi: <b>{_esc(label)}</b> (<code>{key}</code>)\n{info}\n"
                         "Ilovani qayta ochsangiz ko'rinadi.", parse_mode="HTML")


async def cmd_skins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app import media
    if not _is_admin(update):
        return
    have = await asyncio.to_thread(dbm.image_keys) | media.static_keys()
    mark = lambda k: "✅" if k in have else "▫️"  # noqa: E731

    parts = ["<b>Qurollar</b> (✅ bor, ▫️ yo'q)"]
    parts += [f"{mark(k)} <code>{k}</code> — {_esc(n)}" for k, (n, _, _v) in SKINS.items()]
    parts += ["", "<b>Case'lar</b>"] + [f"{mark('case_' + c['id'])} <code>case_{c['id']}</code> — {_esc(c['name'])}"
                                        for c in CASE_LIST]
    parts += ["", "<b>O'yinlar</b>"] + [f"{mark('game_' + g)} <code>game_{g}</code> — {n}" for g, n in media.GAMES.items()]
    parts += [f"{mark('crash_plane')} <code>crash_plane</code> — Crash samolyoti (fonsiz PNG, burni o'ngga)"]
    parts += ["", "<b>Ovozlar</b> (MP3/OGG, 2 MB gacha)"] + [f"{mark(k)} <code>{k}</code> — {d}"
                                                            for k, d in media.SOUNDS.items()]
    parts += ["", "Rasm yoki ovoz yuborib, izohiga kalitni yozing.",
              "O'chirish: <code>/delimg kalit</code>"]
    text = "\n".join(parts)
    for i in range(0, len(text), 3800):  # Telegram xabar chegarasi
        await update.message.reply_text(text[i:i + 3800], parse_mode="HTML")


async def cmd_delimg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app.images import forget
    if not _is_admin(update):
        return
    key = _resolve_key(" ".join(ctx.args or []))
    if not key:
        await update.message.reply_text("Format: /delimg awp_asi")
        return
    ok = await asyncio.to_thread(dbm.delete_skin_image, key)
    forget(key)
    await update.message.reply_text("🗑 O'chirildi" if ok else "Bu kalit uchun fayl yo'q")


# ── Statistika va chiqarishni boshqarish (admin) ──────────────────────

STAR_USD = 0.013   # dasturchi Stars'ni Fragment orqali yechganda taxminan shuncha $ oladi


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app.api import withdraw_enabled
    if not _is_admin(update):
        return
    st = await asyncio.to_thread(dbm.admin_stats)
    on = await asyncio.to_thread(withdraw_enabled)
    usd = lambda n: f"≈ ${n * STAR_USD:,.0f}".replace(",", " ")  # noqa: E731
    f = lambda n: f"{int(n):,}".replace(",", " ")  # noqa: E731
    await update.message.reply_text(
        "<b>📊 CaseVault statistikasi</b>\n\n"
        f"👥 O'yinchilar: <b>{f(st['users'])}</b> (bugun +{f(st['users_day'])})\n"
        f"💳 To'lovlar: <b>{f(st['pay_count'])}</b> ta, {f(st['payers'])} kishidan\n"
        f"⭐ Tushgan Stars: <b>{f(st['pay_stars'])}</b> {usd(st['pay_stars'])}\n"
        f"   bugun: {f(st['pay_stars_day'])} ⭐\n\n"
        f"🎮 O'yinlardan foyda: {f(st['games_profit'])} ⭐\n"
        f"💰 O'yinchilar balansida: {f(st['balances'])} ⭐\n"
        f"🎒 Inventarlardagi skinlar: {f(st['inv_value'])} ⭐ {usd(st['inv_value'])}\n\n"
        f"📦 Steam so'rovlari: {f(st['wd_pending'])} kutilmoqda ({f(st['wd_pending_value'])} ⭐), {f(st['wd_sent'])} yuborilgan\n"
        f"🔓 Steam'ga chiqarish: <b>{'OCHIQ' if on else 'YOPIQ'}</b>\n\n"
        "<i>$ — taxminiy, Stars'ni Fragment orqali yechganda olinadigan summa.</i>",
        parse_mode="HTML")


async def cmd_withdraw_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    on = update.message.text.startswith("/withdraw_on")
    await asyncio.to_thread(dbm.set_setting, "withdraw_enabled", "1" if on else "0")
    await update.message.reply_text(
        "🔓 Steam'ga chiqarish OCHILDI. O'yinchilar so'rov yubora oladi." if on else
        "🔒 Steam'ga chiqarish YOPILDI. Ilovada «tez orada ochiladi» deb ko'rinadi.")


async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    status = "✅ Siz adminsiz" if _is_admin(update) else (
        "❌ Admin emassiz.\nRender → Environment → <code>ADMIN_CHAT_ID</code> ga shu raqamni yozing va qayta deploy qiling."
        if ADMIN_CHAT_ID else "⚠️ ADMIN_CHAT_ID hali sozlanmagan.")
    await update.message.reply_text(f"Sizning Telegram ID: <code>{uid}</code>\n{status}", parse_mode="HTML")


async def cmd_admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    await update.message.reply_text(
        "<b>Admin buyruqlari</b>\n\n"
        "/stats — to'lovlar va foyda statistikasi\n"
        "/withdraw_on — Steam'ga chiqarishni ochish\n"
        "/withdraw_off — yopish\n"
        "/pending — Steam so'rovlari\n"
        "/confirm_ID — yuborildi\n"
        "/reject_ID sabab — rad etish (skin qaytadi)\n"
        "/skins — rasm va ovoz kalitlari ro'yxati\n"
        "Rasm/ovoz + izohda kalit — yuklash\n"
        "/delimg kalit — o'chirish\n"
        "/myid — Telegram ID",
        parse_mode="HTML")


# ── Ilova ─────────────────────────────────────────────────────────────

def build_app() -> Application:
    global _app
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)          # webhook ishlatamiz, polling kerak emas
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("me", cmd_me))
    application.add_handler(CommandHandler("setsteam", cmd_setsteam))
    application.add_handler(CommandHandler("pending", cmd_pending))
    application.add_handler(CommandHandler("skins", cmd_skins))
    application.add_handler(CommandHandler("delimg", cmd_delimg))
    application.add_handler(CommandHandler("admin", cmd_admin_help))
    application.add_handler(CommandHandler("myid", cmd_myid))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler(["withdraw_on", "withdraw_off"], cmd_withdraw_toggle))
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE | filters.AUDIO
                                    | filters.VOICE | filters.Document.AUDIO), on_admin_media))
    application.add_handler(MessageHandler(filters.Regex(_ADMIN_RE), cmd_admin_action))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_error_handler(on_error)
    _app = application
    return application


def get_app() -> Application:
    if _app is None:
        raise RuntimeError("Bot hali ishga tushmagan")
    return _app


def get_bot():
    return get_app().bot
