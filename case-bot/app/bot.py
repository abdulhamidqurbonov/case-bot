import json
import asyncio
import threading
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    PreCheckoutQueryHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from app.config import BOT_TOKEN, WEBAPP_URL, ADMIN_CHAT_ID
from app.database import (
    get_or_create_user, save_payment, set_steam_url
)
from app.prizes import PACKAGES

_app: Application = None
bot_instance = None


# ── /start ────────────────────────────────────────────────────────────
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

    # Referal bonus
    if ref_id and ref_id != user.id:
        from app.database import supabase
        already = supabase.table("referrals") \
            .select("id") \
            .eq("referred_id", user.id) \
            .execute()
        if not already.data:
            supabase.table("referrals").insert({
                "referrer_id": ref_id,
                "referred_id": user.id,
            }).execute()
            supabase.table("users").update({"premium_cases": db_user["premium_cases"] + 1}) \
                .eq("telegram_id", ref_id).execute()
            try:
                await ctx.bot.send_message(
                    ref_id,
                    "🎉 Yangi referal! +1 Premium Case hisobingizga qo'shildi!"
                )
            except Exception:
                pass

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎮 O'yinni boshlash", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await update.message.reply_text(
        f"👋 Salom, {user.first_name}!\n\n"
        "🔫 <b>CS2 Cases Bot</b> ga xush kelibsiz!\n\n"
        "• Case oching va skinlar yutib oling\n"
        "• Har kuni bepul case sizni kutmoqda 🎁\n"
        "• Yutgan skinlarni Steam orqali oling\n\n"
        "⬇️ Bosing va boshlang!",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ── /me — profil ─────────────────────────────────────────────────────
async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = get_or_create_user(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👤 <b>Profilingiz</b>\n\n"
        f"💎 Premium caselar: <b>{db_user['premium_cases']}</b>\n"
        f"⭐ Stars balansi: <b>{db_user['stars_balance']}</b>\n"
        f"🔗 Steam URL: {'✅ Qo\'shilgan' if db_user.get('steam_trade_url') else '❌ Qo\'shilmagan'}",
        parse_mode="HTML"
    )


# ── /setsteam — Steam Trade URL saqlash ──────────────────────────────
async def cmd_setsteam(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "📋 <b>Steam Trade URL qo'shish:</b>\n\n"
            "1. Steam → Inventar → Trade offers → Trade URL\n"
            "2. Quyidagi formatda yuboring:\n\n"
            "<code>/setsteam https://steamcommunity.com/tradeoffer/new/?partner=...</code>",
            parse_mode="HTML"
        )
        return
    url = args[0]
    if "steamcommunity.com/tradeoffer" not in url:
        await update.message.reply_text("❌ Noto'g'ri URL. Steam trade link bo'lishi kerak.")
        return
    set_steam_url(user.id, url)
    await update.message.reply_text(
        "✅ Steam Trade URL saqlandi!\n"
        "Endi skinlarni Steam orqali olishingiz mumkin."
    )


# ── Pre-checkout (Stars to'lov tasdiqlash) ────────────────────────────
async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


# ── Muvaffaqiyatli to'lov ─────────────────────────────────────────────
async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pay     = update.message.successful_payment
    payload = json.loads(pay.invoice_payload)
    user    = update.effective_user
    pkg     = PACKAGES.get(payload.get("package"))

    if not pkg:
        return

    save_payment(user.id, pay.total_amount, pkg["cases"], pay.telegram_payment_charge_id)
    get_or_create_user(user.id, user.username, user.first_name)

    await update.message.reply_text(
        f"✅ <b>To'lov qabul qilindi!</b>\n\n"
        f"💎 {pkg['cases']} ta Premium Case hisobingizga qo'shildi!\n"
        f"⭐ {pay.total_amount} Stars sarflandi\n\n"
        f"Botga kiring va case oching! 🎮",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎮 Case ochish", web_app=WebAppInfo(url=WEBAPP_URL))
        ]])
    )


# ── Admin: chiqarish so'rovlari ───────────────────────────────────────
async def admin_withdraw_notify(prize_name: str, steam_url: str, username: str, req_id: int):
    """Adminga chiqarish so'rovi haqida xabar yuborish"""
    if not bot_instance or not ADMIN_CHAT_ID:
        return
    text = (
        f"📦 <b>Yangi chiqarish so'rovi #{req_id}</b>\n\n"
        f"👤 Foydalanuvchi: @{username or 'Noma\'lum'}\n"
        f"🔫 Skin: <b>{prize_name}</b>\n"
        f"🔗 Trade URL: <code>{steam_url}</code>\n\n"
        f"Yuborish tugagach /confirm_{req_id} yuboring"
    )
    await bot_instance.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML")


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin skin yuborgandan keyin tasdiqlash"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    text = update.message.text or ""
    try:
        req_id = int(text.replace("/confirm_", "").strip())
    except ValueError:
        await update.message.reply_text("❌ Format: /confirm_123")
        return

    from app.database import supabase
    from datetime import datetime, timezone

    req = supabase.table("withdraw_requests").select("*").eq("id", req_id).single().execute().data
    if not req:
        await update.message.reply_text("❌ So'rov topilmadi")
        return

    supabase.table("withdraw_requests").update({
        "status":       "sent",
        "processed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", req_id).execute()
    supabase.table("inventory").update({"status": "withdrawn"}).eq("id", req["inventory_id"]).execute()

    try:
        await bot_instance.send_message(
            req["telegram_id"],
            f"✅ <b>Skin yuborildi!</b>\n\n"
            f"🔫 {req['prize_name']} Steam ga yuborildi.\n"
            f"Trade offeringizni tekshiring!",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await update.message.reply_text(f"✅ #{req_id} tasdiqlandi va foydalanuvchiga xabar yuborildi.")


# ── Bot ishga tushirish ───────────────────────────────────────────────
def start_bot():
    global _app, bot_instance
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN yo'q")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    _app = Application.builder().token(BOT_TOKEN).build()
    bot_instance = _app.bot

    _app.add_handler(CommandHandler("start",   cmd_start))
    _app.add_handler(CommandHandler("me",      cmd_me))
    _app.add_handler(CommandHandler("setsteam", cmd_setsteam))
    _app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    _app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    _app.add_handler(MessageHandler(filters.Regex(r"^/confirm_\d+$"), cmd_confirm))

    print("🤖 Bot polling ishga tushdi")
    _app.run_polling(close_loop=False)


def run_bot_thread():
    t = threading.Thread(target=start_bot, daemon=True)
    t.start()
