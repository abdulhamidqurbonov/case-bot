"""Barcha sozlamalar shu yerda — qiymatlar Render Environment (yoki lokal .env) dan olinadi."""
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ── Majburiy ──────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
WEBAPP_URL   = os.getenv("WEBAPP_URL", "").strip().rstrip("/")

# ── Ixtiyoriy ─────────────────────────────────────────────────────────
ADMIN_CHAT_ID    = _int("ADMIN_CHAT_ID", 0)
BOT_USERNAME     = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "").strip()
PORT             = _int("PORT", 8000)

FREE_CASE_COOLDOWN_H = _int("FREE_CASE_COOLDOWN_HOURS", 24)
REFERRAL_BONUS_STARS = _int("REFERRAL_BONUS_STARS", 10)    # taklif qilgan odamga
TASK_BONUS_STARS     = _int("TASK_BONUS_STARS", 10)        # kanalga obuna uchun
SELL_RATE_PERCENT    = _int("SELL_RATE_PERCENT", 100)      # skin qiymatining necha % i qaytadi
INIT_DATA_MAX_AGE_S  = _int("INIT_DATA_MAX_AGE_SECONDS", 86400)

# Iqtisod: o'yinchiga o'rtacha qaytadigan foiz (RTP). Qolgani — sizning daromadingiz.
CASE_RTP_PERCENT     = _int("CASE_RTP_PERCENT", 90)
UPGRADE_RTP_PERCENT  = _int("UPGRADE_RTP_PERCENT", 90)
CONTRACT_RTP_PERCENT = _int("CONTRACT_RTP_PERCENT", 90)
CRASH_RTP_PERCENT    = _int("CRASH_RTP_PERCENT", 93)
DICE_RTP_PERCENT     = _int("DICE_RTP_PERCENT", 95)

MIN_BET   = _int("MIN_BET", 5)
MAX_BET   = _int("MAX_BET", 50000)
MAX_WIN   = _int("MAX_WIN", 500000)          # bitta o'yindagi eng katta yutuq

# Steam'ga chiqarish qoidalari (aldovdan himoya)
MIN_WITHDRAW_VALUE    = _int("MIN_WITHDRAW_VALUE", 100)   # bundan arzon skin chiqarilmaydi
WITHDRAW_MIN_DEPOSIT  = _int("WITHDRAW_MIN_DEPOSIT", 500) # jami shuncha Stars to'lagan bo'lishi kerak
WITHDRAW_ENABLED      = _int("WITHDRAW_ENABLED", 0)       # boshlang'ich holat; keyin bot: /withdraw_on, /withdraw_off

# Render bepul tarifida server 15 daqiqa so'rovsiz qolsa uxlaydi. 1 = server o'zini har 10 daqiqada
# tashqi manzil orqali «uyg'otib» turadi (WEBAPP_URL/health). 0 = o'chirilgan.
KEEP_ALIVE = _int("KEEP_ALIVE", 1)

# ── Qaytarish eslatmalari: kirmay qo'ygan o'yinchiga «bepul case tayyor» xabari ──
REMIND_ENABLED = _int("REMIND_ENABLED", 1)        # boshlang'ich holat; keyin bot: /remind_on, /remind_off
REMIND_AFTER_H = _int("REMIND_AFTER_HOURS", 20)   # oxirgi kirishdan necha soat o'tgach birinchi eslatma

# ── AI (Groq — groq.com, bepul tarifi bor, juda tez) ───────────────────
# console.groq.com → API Keys. Kalit bo'lmasa AI funksiyalari shunchaki o'chiq turadi.
AI_API_KEY   = (os.getenv("GROQ_API_KEY", "") or os.getenv("AI_API_KEY", "")).strip()
AI_MODEL     = os.getenv("AI_MODEL", "openai/gpt-oss-120b").strip()
# Limit tugasa yoki asosiy model ishlamasa — shu model ishlatiladi
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "llama-3.3-70b-versatile").strip()
AI_BASE_URL  = os.getenv("AI_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
SUPPORT_AI   = _int("SUPPORT_AI", 1)              # 1 = o'yinchilarga AI yordam (ilova + botga yozilgan xabar)
SUPPORT_DAILY_LIMIT = _int("SUPPORT_DAILY_LIMIT", 30)   # bitta o'yinchi kuniga nechta savol bera oladi
AI_DAILY_HOUR = _int("AI_DAILY_HOUR", 21)         # /ai_daily hisoboti soati (Toshkent vaqti)

# Ixtiyoriy: ilova sahifasi uxlamaydigan bepul hostingda (GitHub Pages / Cloudflare Pages).
# Berilsa, bot tugmalari shu manzilni ochadi va Render'ning «Application loading» sahifasi hech qachon chiqmaydi.
# Masalan: https://abdulhamidqurbonov.github.io/case-bot
FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip().rstrip("/")


def app_url(case_id: str | None = None) -> str:
    """Telegram'dagi «O'yin» tugmalari ochadigan manzil."""
    from urllib.parse import urlencode
    if FRONTEND_URL:
        q = {"api": WEBAPP_URL}
        if case_id:
            q["case"] = case_id
        return FRONTEND_URL + "/?" + urlencode(q)
    return WEBAPP_URL + (f"/?case={case_id}" if case_id else "/")


# Webhook maxfiy kaliti. Berilmasa, tokendan avtomatik yasaladi
# (tokenning o'zi hech qayerda ochiq ko'rinmaydi).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip() or (
    hashlib.sha256(("webhook:" + BOT_TOKEN).encode()).hexdigest()[:48]
)


def missing_required() -> list[str]:
    """Bo'sh qolgan majburiy o'zgaruvchilar ro'yxati."""
    return [name for name, val in (
        ("BOT_TOKEN", BOT_TOKEN),
        ("DATABASE_URL", DATABASE_URL),
        ("WEBAPP_URL", WEBAPP_URL),
    ) if not val]
