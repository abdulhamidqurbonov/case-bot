import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PreCheckoutQueryHandler, filters, ContextTypes
)
from app.config import BOT_TOKEN, WEBAPP_URL, ADMIN_CHAT_ID
from app.database import get_or_create_user, save_payment, set_steam_url
from app.prizes import PACKAGES

logger = logging.getLogger(__name__)

_app: Application = None
bot_instance = None


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    ref_id = None
    for part in text.split():
        if part.startswith("ref_"):
            try:
                ref_id = int(part[4:])
            except ValueError:
                pass

    db_user = get_or_create_user(user.id, user.username, user.first_name)

    if ref_id and ref_id != user.id:
        from app.database import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM referrals WHERE referred_id=%s",
                    (user.id,)
                )
                already = cur.fetchone()
                if not already:
                    cur.execute(
                        "INSERT INTO referrals (referrer_id, referred_id) VALUES (%s,%s)",
                        (ref_id, user.id)
                    )
                    cur.execute(
                        "UPDATE users SET premium_cases=premium_cases+1 WHERE telegram_id=%s",
                        (ref_id,)
                    )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()
        try:
            await ctx.bot.send_message(
                ref_id,
                "Yangi referal! +1 Premium Case hisobingizga qoshildi!"
            )
        except Exception:
            pass

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Oyinni boshlash", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    name = user.first_name or "Foydalanuvchi"
    await update.message.reply_text(
        "<b>CS2 Cases Bot</b> ga xush kelibsiz, " + name + "!\n\n"
        "Case oching va skinlar yutib oling!\n"
        "Har kuni bepul case sizni kutmoqda\n\n"
        "Bosing va boshlang!",
        reply_markup=kb,
        parse_mode="HTML"
    )


async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.first_name)
    has_steam = db_user.get("steam_trade_url")
    steam_txt = "Qoshilgan" if has_steam else "Yoq — /setsteam bilan qoshing"
    await update.message.reply_text(
        "<b>Profilingiz</b>\n\n"
        "Premium caselar: <b>" + str(db_user["premium_cases"]) + "</b>\n"
        "Stars balansi: <b>" + str(db_user["stars_balance"]) + "</b>\n"
        "Steam URL: " + steam_txt,
        parse_mode="HTML"
    )


async def cmd_setsteam(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "<b>Steam Trade URL qoshish:</b>\n\n"
            "Steam → Inventar → Trade offers → Trade URL\n\n"
            "Format:\n"
            "<code>/setsteam https://steamcommunity.com/tradeoffer/new/?partner=...</code>",
            parse_mode="HTML"
        )
        return
    url = args[0]
    if "steamcommunity.com/tradeoffer" not in url:
        await update.message.reply_text("Notogri URL. Steam trade link bolishi kerak.")
        return
    set_steam_url(user.id, url)
    await update.message.reply_text("Steam Trade URL saqlandi!")


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pay     = update.message.successful_payment
    payload = json.loads(pay.invoice_payload)
    user    = update.effective_user
    pkg     = PACKAGES.get(payload.get("package"))
    if not pkg:
        return
    save_payment(user.id, pay.total_amount, pkg["cases"], pay.telegram_payment_charge_id)
    await update.message.reply_text(
        "<b>Tolov qabul qilindi!</b>\n\n"
        + str(pkg["cases"]) + " ta Premium Case hisobingizga qoshildi!\n"
        + str(pay.total_amount) + " Stars sarflandi",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Case ochish", web_app=WebAppInfo(url=WEBAPP_URL))
        ]])
    )


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    text = update.message.text or ""
    try:
        req_id = int(text.replace("/confirm_", "").strip())
    except ValueError:
        await update.message.reply_text("Format: /confirm_123")
        return

    from app.database import confirm_withdraw
    req = confirm_withdraw(req_id)
    if not req:
        await update.message.reply_text("Sorov topilmadi")
        return

    try:
        await bot_instance.send_message(
            req["telegram_id"],
            "<b>Skin yuborildi!</b>\n\n"
            + str(req["prize_name"]) + " Steam ga yuborildi.\n"
            "Trade offeringizni tekshiring!",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await update.message.reply_text("Tasdiqlandi — #" + str(req_id))


def build_app() -> Application:
    global _app, bot_instance
    application = Application.builder().token(BOT_TOKEN).build()
    bot_instance = application.bot

    application.add_handler(CommandHandler("start",    cmd_start))
    application.add_handler(CommandHandler("me",       cmd_me))
    application.add_handler(CommandHandler("setsteam", cmd_setsteam))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.Regex(r"^/confirm_\d+$"), cmd_confirm))

    _app = application
    return application


def get_app() -> Application:
    global _app
    if _app is None:
        build_app()
    return _app