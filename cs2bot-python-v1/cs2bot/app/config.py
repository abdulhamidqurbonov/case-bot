import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN              = os.getenv("BOT_TOKEN", "")
WEBAPP_URL             = os.getenv("WEBAPP_URL", "")
ADMIN_CHAT_ID          = int(os.getenv("ADMIN_CHAT_ID", "0"))
SUPABASE_URL           = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY           = os.getenv("SUPABASE_KEY", "")
FREE_CASE_COOLDOWN_H   = int(os.getenv("FREE_CASE_COOLDOWN_HOURS", "24"))
MIN_WITHDRAW_STARS     = int(os.getenv("MIN_WITHDRAW_STARS", "500"))
PORT                   = int(os.getenv("PORT", "8000"))
