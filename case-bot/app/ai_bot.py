"""Botdagi AI: admin uchun /ai, o'yinchilar uchun botga yozilgan savollarga support javobi."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from app import ai
from app import database as dbm
from app.config import app_url

logger = logging.getLogger(__name__)
_is_admin = None

AI_ERRORS = {
    "bad_key": "Groq kaliti noto'g'ri yoki o'chirilgan. console.groq.com → API Keys ni tekshiring.",
    "rate_limit": "Groq bepul limiti shu daqiqaga tugadi. 1 daqiqadan keyin qayta yozing.",
    "too_long": "Savol juda katta bo'ldi. /ai_reset qilib, qisqaroq yozing.",
    "network": "AI serveriga ulanib bo'lmadi. Birozdan keyin qayta urinib ko'ring.",
    "api_error": "AI javob bermadi. Birozdan keyin qayta urinib ko'ring.",
    "disabled": "AI o'chiq: Render → Environment ga GROQ_API_KEY qo'shing.",
}

SETUP_TEXT = (
    "🤖 <b>AI hali ulanmagan</b>\n\n"
    "1. <a href=\"https://console.groq.com/keys\">console.groq.com/keys</a> ga kiring (Google bilan) → <b>Create API Key</b>\n"
    "2. Kalitni nusxalang (gsk_... bilan boshlanadi)\n"
    "3. Render → servisingiz → <b>Environment</b> → <code>GROQ_API_KEY</code> = kalit → Save\n"
    "4. Deploy tugagach yana /ai yozing.\n\n"
    "<i>Kalitni hech kimga, hatto chatga ham yubormang.</i>")


async def _typing(chat, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:  # noqa: BLE001
            pass
        try:
            await asyncio.wait_for(stop.wait(), 4.5)
        except asyncio.TimeoutError:
            pass


async def _with_typing(update: Update, coro):
    stop = asyncio.Event()
    t = asyncio.create_task(_typing(update.effective_chat, stop))
    try:
        return await coro
    finally:
        stop.set()
        t.cancel()


async def send_md(message, text: str, reply_markup=None):
    parts = ai.split_text(text)
    for i, part in enumerate(parts):
        kb = reply_markup if i == len(parts) - 1 else None
        try:
            await message.reply_text(ai.md_to_html(part), parse_mode="HTML", reply_markup=kb,
                                     disable_web_page_preview=True)
        except BadRequest:
            await message.reply_text(part, reply_markup=kb, disable_web_page_preview=True)


# ── Admin ─────────────────────────────────────────────────────────────

async def _admin_answer(update: Update, text: str):
    try:
        answer = await _with_typing(update, ai.admin_ask(update.effective_user.id, text))
    except ai.AIError as e:
        await update.message.reply_text("⚠️ " + AI_ERRORS.get(e.code, AI_ERRORS["api_error"]))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Admin AI xatosi")
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.")
        return
    await send_md(update.message, answer)


async def cmd_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not ai.enabled():
        await update.message.reply_text(SETUP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
        return
    ctx.user_data["ai_mode"] = True
    q = " ".join(ctx.args or []).strip()
    if q:
        await _admin_answer(update, q)
        return
    await update.message.reply_text(
        "🤝 <b>AI biznes hamkor yoqildi</b> — endi shunchaki yozing, xuddi sherigingiz bilan gaplashgandek.\n\n"
        "Masalan:\n"
        "• <i>Bugungi statistika qanday?</i>\n"
        "• <i>@username hozir nima qilyapti?</i>\n"
        "• <i>Kim xato qilyapti, nimada qiynalishyapti?</i>\n"
        "• <i>Odam ko'paytirish uchun 5 ta g'oya ber</i>\n"
        "• <i>Qaysi case va o'yin ko'proq foyda beryapti?</i>\n"
        "• <i>O'yinchilar supportga nima deb yozyapti?</i>\n"
        "• <i>Keyingi oy uchun o'sish rejasini tuzamiz</i>\n\n"
        "/ai_off — o'chirish · /ai_reset — suhbatni tozalash · /ai_daily — har kuni hisobot",
        parse_mode="HTML")


async def cmd_ai_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    ctx.user_data.pop("ai_mode", None)
    await update.message.reply_text("🤖 AI rejimi o'chirildi. Qayta yoqish: /ai")


async def cmd_ai_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    await asyncio.to_thread(dbm.ai_clear, "admin", update.effective_user.id)
    await update.message.reply_text("🧹 AI suhbat tarixi tozalandi.")


async def cmd_ai_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app.config import AI_DAILY_HOUR
    if not _is_admin(update):
        return
    on = await asyncio.to_thread(dbm.get_setting, "ai_daily", "0") == "1"
    await asyncio.to_thread(dbm.set_setting, "ai_daily", "0" if on else "1")
    await update.message.reply_text(
        "🗓 Kunlik AI hisobot o'chirildi." if on else
        f"🗓 Kunlik AI hisobot yoqildi: har kuni soat {AI_DAILY_HOUR}:00 da (Toshkent) statistika, "
        "muammolar va ertangi kun uchun g'oyalar keladi.\n<i>Server o'sha paytda uyg'oq bo'lishi kerak.</i>",
        parse_mode="HTML")


# ── Matnli xabarlar (admin AI rejimi yoki o'yinchi support) ───────────

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or ctx.user_data.get("nc"):      # /newcase dialogi davom etyapti
        return
    user = update.effective_user
    if _is_admin(update):
        if ctx.user_data.get("ai_mode") and ai.enabled():
            await _admin_answer(update, msg.text)
        elif ai.enabled():
            await msg.reply_text("🤖 AI bilan gaplashish uchun /ai yozing (yoki: /ai savolingiz)")
        return
    if not ai.support_enabled():
        return
    try:
        res = await _with_typing(update, ai.support_ask(user.id, msg.text, user.username, user.first_name))
    except ai.SupportLimit as e:
        text = {"daily_limit": "Bugungi savollar limiti tugadi. Ertaga yana yozing yoki ilovadagi Profil bo'limini ko'ring.",
                "too_fast": "⏳ Bir soniya, oldingi savolingizga javob tayyorlanyapti…"}.get(e.code)
        if text:
            await msg.reply_text(text)
        return
    except ai.AIError:
        await msg.reply_text("Hozir javob bera olmayapman. Birozdan keyin qayta yozing 🙏")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Ilovani ochish", web_app=WebAppInfo(url=app_url()))]])
    await msg.reply_text(res["reply"][:4000], reply_markup=kb, disable_web_page_preview=True)


def register(application, is_admin) -> None:
    global _is_admin
    _is_admin = is_admin
    application.add_handler(CommandHandler("ai", cmd_ai, block=False))
    application.add_handler(CommandHandler("ai_off", cmd_ai_off))
    application.add_handler(CommandHandler("ai_reset", cmd_ai_reset))
    application.add_handler(CommandHandler("ai_daily", cmd_ai_daily))
    # AI javobi 5–30 soniya olishi mumkin — webhook'ni ushlab turmaslik uchun fonda (block=False)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                                           on_text, block=False))
