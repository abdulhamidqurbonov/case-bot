"""Botdagi AI: admin uchun /ai, o'yinchilar uchun botga yozilgan savollarga support javobi."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app import ai, engage
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


# ── Tasdiqlanadigan amallar ───────────────────────────────────────────

def _proposal_kb(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"aiact:{pid}:ok"),
                                  InlineKeyboardButton("❌ Bekor", callback_data=f"aiact:{pid}:no")]])


async def send_proposals(bot, chat_id: int, proposals: list[str]) -> None:
    for pid in proposals:
        p = ai.PENDING.get(pid)
        if not p:
            continue
        text = "🤝 <b>AI taklif qilyapti — tasdiqlaysizmi?</b>\n\n" + ai.describe(p)
        try:
            await bot.send_message(chat_id, text[:4000], parse_mode="HTML", reply_markup=_proposal_kb(pid),
                                   disable_web_page_preview=True)
        except BadRequest:
            await bot.send_message(chat_id, "🤝 AI taklifi:\n\n" + str(p.get("text") or p)[:3500],
                                   reply_markup=_proposal_kb(pid))


async def send_admin(bot, text: str, proposals: list[str] | None = None) -> None:
    """Avtopilot va hisobotlar uchun: adminga xabar + tasdiqlash tugmalari."""
    from app.config import ADMIN_CHAT_ID
    for part in ai.split_text(text):
        try:
            await bot.send_message(ADMIN_CHAT_ID, ai.md_to_html(part), parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest:
            await bot.send_message(ADMIN_CHAT_ID, part, disable_web_page_preview=True)
    await send_proposals(bot, ADMIN_CHAT_ID, proposals or [])


async def _execute(bot, admin_chat: int, p: dict) -> str:
    from app import admin_cases
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    k = p["kind"]
    if k == "broadcast":
        if admin_cases._bcast_lock.locked():
            return "⏳ Oldingi e'lon hali yuborilmoqda — tugagach qayta so'rang."
        asyncio.get_running_loop().create_task(
            admin_cases._broadcast(bot, admin_chat, "text", ai.md_to_html(p["text"])))
        return "📢 E'lon yuborilmoqda — holati alohida xabarda."
    if k == "message":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 O'ynash", web_app=WebAppInfo(url=app_url()))]])
        await bot.send_message(p["uid"], ai.md_to_html(p["text"]), parse_mode="HTML", reply_markup=kb,
                               disable_web_page_preview=True)
        return "✉️ Xabar yuborildi."
    if k == "gift":
        bal = await asyncio.to_thread(dbm.change_balance, p["uid"], p["amount"], "admin_gift", "ai")
        try:
            await bot.send_message(p["uid"], f"🎁 Sizga <b>{p['amount']} ⭐</b> sovg'a qilindi!\n{esc(p['reason'])}",
                                   parse_mode="HTML")
        except Exception:  # noqa: BLE001
            pass
        return f"🎁 {p['amount']} ⭐ qo'shildi. O'yinchi balansi: {bal} ⭐"
    if k == "withdraw":
        await asyncio.to_thread(dbm.set_setting, "withdraw_enabled", "1" if p["enabled"] else "0")
        return "🔓 Steam'ga chiqarish OCHILDI." if p["enabled"] else "🔒 Steam'ga chiqarish YOPILDI."
    return "Noma'lum amal."


async def on_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_admin(update):
        await q.answer("Faqat admin uchun", show_alert=True)
        return
    _, pid, choice = (q.data.split(":") + ["", ""])[:3]
    p = ai.PENDING.pop(pid, None)
    if not p:
        await q.answer("Bu taklif eskirgan yoki bajarilgan", show_alert=True)
        await q.edit_message_reply_markup(None)
        return
    if choice != "ok":
        await q.answer("Bekor qilindi")
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("❌ Bekor qilindi.")
        return
    await q.answer("Bajarilmoqda…")
    await q.edit_message_reply_markup(None)
    try:
        result = await _execute(ctx.bot, q.message.chat_id, p)
    except Exception as e:  # noqa: BLE001
        logger.exception("AI amali bajarilmadi")
        result = f"⚠️ Bajarilmadi: {e.__class__.__name__}"
    await q.message.reply_text("✅ " + result if not result.startswith(("⚠️", "⏳")) else result)


# ── Admin ─────────────────────────────────────────────────────────────

def _mode_key(uid: int) -> str:
    return f"ai_mode:{uid}"


async def _ai_mode(ctx, uid: int) -> bool:
    """AI rejimi bazada saqlanadi — server qayta ishga tushsa ham yoqiq qoladi."""
    if "ai_mode" not in ctx.user_data:
        ctx.user_data["ai_mode"] = await asyncio.to_thread(dbm.get_setting, _mode_key(uid), "0") == "1"
    return ctx.user_data["ai_mode"]


async def _set_mode(ctx, uid: int, on: bool) -> None:
    ctx.user_data["ai_mode"] = on
    await asyncio.to_thread(dbm.set_setting, _mode_key(uid), "1" if on else "0")


async def _admin_answer(update: Update, text: str):
    try:
        answer, proposals = await _with_typing(update, ai.admin_ask(update.effective_user.id, text))
    except ai.AIError as e:
        await update.message.reply_text("⚠️ " + AI_ERRORS.get(e.code, AI_ERRORS["api_error"]))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Admin AI xatosi")
        await update.message.reply_text("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.")
        return
    await send_md(update.message, answer)
    await send_proposals(update.get_bot(), update.effective_chat.id, proposals)


async def cmd_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not ai.enabled():
        await update.message.reply_text(SETUP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
        return
    await _set_mode(ctx, update.effective_user.id, True)
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
        "• <i>Keyingi oy uchun o'sish rejasini tuzamiz</i>\n"
        "• <i>Hammaga yangi case haqida e'lon tayyorla</i>\n"
        "• <i>@username ga 50 ⭐ kompensatsiya ber</i>\n\n"
        "Pul yoki hammaga xabar bilan bog'liq amallarni AI faqat taklif qiladi — siz «✅ Tasdiqlash» ni bosasiz.\n\n"
        "Rejim server qayta ishga tushsa ham yoqiq qoladi.\n"
        "/ai_off — o'chirish · /ai_reset — suhbatni tozalash\n"
        "/ai_auto — avtopilot (siz yo'qligingizda kuzatadi) · /ai_daily — kunlik hisobot\n"
        "/remind_stats — qaytarish eslatmalari",
        parse_mode="HTML")


async def cmd_ai_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    await _set_mode(ctx, update.effective_user.id, False)
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


async def cmd_ai_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from app.config import AI_DAILY_HOUR
    if not _is_admin(update):
        return
    if not ai.enabled():
        await update.message.reply_text(SETUP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
        return
    on = await asyncio.to_thread(dbm.get_setting, "ai_auto", "0") == "1"
    await asyncio.to_thread(dbm.set_setting, "ai_auto", "0" if on else "1")
    if on:
        await update.message.reply_text("🛰 Avtopilot o'chirildi. (Qaytarish eslatmalari alohida: /remind_off)")
        return
    await update.message.reply_text(
        "🛰 <b>Avtopilot yoqildi.</b> Siz yo'qligingizda AI botni kuzatadi:\n\n"
        "• ☀️ 10:00 — bugungi reja (kerak bo'lsa tayyor e'lon taklifi)\n"
        "• 🔎 har 3 soatda tekshiruv — faqat muhim narsa bo'lsa yozadi: Steam so'rovi kutib qolgan, "
        "xatolar ko'paygan, ko'p yutqazayotgan o'yinchi\n"
        f"• 🗓 {AI_DAILY_HOUR}:00 — kunlik hisobot va ertangi g'oyalar\n"
        "• 💬 o'yinchilar savollariga support AI javob beradi, hal qila olmasa sizga yuboradi\n"
        "• 🎁 kirmay qo'yganlarga «bepul case tayyor» eslatmasi (/remind_stats)\n\n"
        "E'lon, Stars sovg'a, chiqarishni ochish — faqat siz «✅ Tasdiqlash» ni bosgandan keyin bajariladi.\n"
        "<i>Server uyg'oq bo'lishi kerak (cron-job.org).</i>",
        parse_mode="HTML")


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    cmd = (update.message.text or "").split()[0].split("@")[0]
    if cmd in ("/remind_on", "/remind_off"):
        await asyncio.to_thread(engage.set_enabled, cmd == "/remind_on")
    if cmd == "/remind_now":
        await update.message.reply_text("⏳ Eslatmalar yuborilmoqda…")
        res = await engage.run_once(ctx.bot, force=True)
        await update.message.reply_text(f"✅ Yuborildi: {res['sent']} · bloklagan: {res['blocked']} · xato: {res['failed']}")
        return
    st = await asyncio.to_thread(engage.stats)
    await update.message.reply_text(
        "🎁 <b>Qaytarish eslatmalari</b> — " + ("✅ YOQIQ" if st["enabled"] else "⛔ O'CHIQ") + "\n\n"
        "Kirmay qo'ygan o'yinchiga «bepul case tayyor» xabari: 1-marta kirmaganiga 20 soat bo'lganda, "
        "keyin +2, +4, +7 kundan so'ng (ko'pi bilan 4 marta). Faqat 10:00–21:00.\n\n"
        f"📨 Oxirgi 24 soatda: <b>{st['sent_24h']}</b>\n"
        f"↩️ 7 kunda eslatma olib, qaytib kirgan: <b>{st['came_back_7d']}</b> / {st['reminded_7d']}\n"
        f"⏳ Hozir navbatda: {st['waiting_now']}\n"
        f"🔕 O'chirib qo'yganlar: {st['opted_out']} · botni bloklagan: {st['blocked_bot']}\n\n"
        "/remind_on · /remind_off · /remind_now — hozir yuborish",
        parse_mode="HTML")


async def on_remind_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await asyncio.to_thread(engage.opt_out, update.effective_user.id)
    await q.answer("Eslatmalar o'chirildi")
    try:
        await q.edit_message_reply_markup(InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎁 Bepul case'ni ochish", web_app=WebAppInfo(url=app_url("free")))]]))
    except Exception:  # noqa: BLE001
        pass


# ── Matnli xabarlar (admin AI rejimi yoki o'yinchi support) ───────────

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or ctx.user_data.get("nc"):      # /newcase dialogi davom etyapti
        return
    user = update.effective_user
    if _is_admin(update):
        if ai.enabled() and await _ai_mode(ctx, user.id):
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
    application.add_handler(CommandHandler("ai_auto", cmd_ai_auto))
    application.add_handler(CommandHandler(["remind_on", "remind_off", "remind_stats", "remind_now"], cmd_remind,
                                           block=False))
    application.add_handler(CallbackQueryHandler(on_action, pattern=r"^aiact:"))
    application.add_handler(CallbackQueryHandler(on_remind_off, pattern=r"^rm:off$"))
    # AI javobi 5–30 soniya olishi mumkin — webhook'ni ushlab turmaslik uchun fonda (block=False)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                                           on_text, block=False))
