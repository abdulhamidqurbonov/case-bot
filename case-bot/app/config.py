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
REFERRAL_BONUS_STARS = _int("REFERRAL_BONUS_STARS", 25)    # taklif qilgan odamga
TASK_BONUS_STARS     = _int("TASK_BONUS_STARS", 25)        # kanalga obuna uchun
SELL_RATE_PERCENT    = _int("SELL_RATE_PERCENT", 10)       # skin qiymatining necha % i qaytadi
INIT_DATA_MAX_AGE_S  = _int("INIT_DATA_MAX_AGE_SECONDS", 86400)

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
