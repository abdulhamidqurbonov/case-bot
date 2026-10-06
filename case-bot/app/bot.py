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
        f"Salom, {name}! 🔥\n\n"
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
    from app.api import _valid_trade_url  # noqa: E402

    if not ctx.args:
        await update.message.reply_text(
            "<b>Steam Trade URL qo'shish:</b>\n\n"
            "Steam → Inventar → Trade offers → Who can send me trade offers → Trade URL\n\n"
            "Format:\n<code>/setsteam https://steamcommunity.com/tradeoffer/new/?partner=...&amp;token=...</code>",
            parse_mode="HTML",
        )
        return
    url = ctx.args[0].strip()
    if not _valid_trade_url(url):
        await update.message.reply_text("❌ Noto'g'ri URL. To'liq Steam trade link yuboring (partner va token bilan).")
        return
    await asyncio.to_thread(dbm.set_steam_url, update.effective_user.id, url)
    await update.message.reply_text("✅ Steam Trade URL saqlandi!")


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


# ── Skin rasmlari (admin) ─────────────────────────────────────────────

_IMAGE_KEYS = set(SKINS) | {"case_" + c["id"] for c in CASE_LIST}
_MAX_IMAGE_BYTES = 3 * 1024 * 1024


def _resolve_image_key(text: str) -> str | None:
    t = (text or "").strip()
    if t.lower() in _IMAGE_KEYS:
        return t.lower()
    return key_by_name(t)


async def on_admin_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin rasm yuboradi, izohiga skin kaliti yoki nomini yozadi."""
    if not _is_admin(update):
        return
    msg = update.message
    key = _resolve_image_key(msg.caption or "")
    if not key:
        await msg.reply_text(
            "Rasm izohiga skin kalitini yozing, masalan: <code>awp_asi</code>\n"
            "Ro'yxat: /skins", parse_mode="HTML")
        return

    if msg.photo:
        file_obj, mime = msg.photo[-1], "image/jpeg"
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_obj, mime = msg.document, msg.document.mime_type
    else:
        return
    if file_obj.file_size and file_obj.file_size > _MAX_IMAGE_BYTES:
        await msg.reply_text("Rasm 3 MB dan katta. Kichikroq rasm yuboring.")
        return

    tg_file = await file_obj.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    await asyncio.to_thread(dbm.save_skin_image, key, data, mime)
    from app.images import forget
    forget(key)
    name = SKINS[key][0] if key in SKINS else key
    await msg.reply_text(f"✅ Rasm saqlandi: <b>{_esc(name)}</b> (<code>{key}</code>)", parse_mode="HTML")


async def cmd_skins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    have = await asyncio.to_thread(dbm.image_keys)
    lines = ["<b>Skinlar</b> (✅ rasm bor, ▫️ yo'q)\n"]
    for k, (name, _, value) in SKINS.items():
        lines.append(f"{'✅' if k in have else '▫️'} <code>{k}</code> — {_esc(name)} · {value}⭐")
    lines.append("\n<b>Case rasmlari</b>")
    for c in CASE_LIST:
        k = "case_" + c["id"]
        lines.append(f"{'✅' if k in have else '▫️'} <code>{k}</code> — {_esc(c['name'])}")
    lines.append("\nRasm yuborib, izohiga kalitni yozing. PNG (fonsiz) uchun — fayl sifatida yuboring.\n"
                 "O'chirish: <code>/delimg kalit</code>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_delimg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    key = _resolve_image_key(" ".join(ctx.args or []))
    if not key:
        await update.message.reply_text("Format: /delimg awp_asi")
        return
    ok = await asyncio.to_thread(dbm.delete_skin_image, key)
    from app.images import forget
    forget(key)
    await update.message.reply_text("🗑 O'chirildi" if ok else "Bu kalit uchun rasm yo'q")


async def cmd_admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    await update.message.reply_text(
        "<b>Admin buyruqlari</b>\n\n"
        "/pending — Steam so'rovlari\n"
        "/confirm_ID — yuborildi\n"
        "/reject_ID sabab — rad etish (skin qaytadi)\n"
        "/skins — rasmlar ro'yxati\n"
        "Rasm + izohda kalit — rasm yuklash\n"
        "/delimg kalit — rasmni o'chirish",
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
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE), on_admin_image))
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
