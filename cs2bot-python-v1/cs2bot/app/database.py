from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Users ─────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).single().execute()

    if res.data:
        # username yangilanishi
        if username and res.data.get("username") != username:
            supabase.table("users").update({"username": username, "first_name": first_name}) \
                .eq("telegram_id", telegram_id).execute()
        return supabase.table("users").select("*").eq("telegram_id", telegram_id).single().execute().data

    # Yangi user
    data = {
        "telegram_id": telegram_id,
        "username":    username,
        "first_name":  first_name,
    }
    supabase.table("users").insert(data).execute()
    return supabase.table("users").select("*").eq("telegram_id", telegram_id).single().execute().data


def set_steam_url(telegram_id: int, url: str):
    supabase.table("users").update({"steam_trade_url": url}).eq("telegram_id", telegram_id).execute()


# ── Case openings ─────────────────────────────────────────────────────

def save_opening(telegram_id: int, case_id: str, prize: dict, was_free: bool) -> dict:
    row = {
        "telegram_id":  telegram_id,
        "case_id":      case_id,
        "prize_name":   prize["name"],
        "prize_image":  prize.get("image", ""),
        "prize_value":  prize["value"],
        "prize_rarity": prize["rarity"],
        "was_free":     was_free,
    }
    supabase.table("case_openings").insert(row).execute()

    # Inventarga ham qo'shish
    inv_row = {
        "telegram_id":  telegram_id,
        "prize_name":   prize["name"],
        "prize_image":  prize.get("image", ""),
        "prize_value":  prize["value"],
        "prize_rarity": prize["rarity"],
        "status":       "active",
    }
    inv = supabase.table("inventory").insert(inv_row).execute()
    return inv.data[0]


def update_free_case_time(telegram_id: int):
    from datetime import datetime, timezone
    supabase.table("users").update({
        "free_case_used_at": datetime.now(timezone.utc).isoformat()
    }).eq("telegram_id", telegram_id).execute()


def deduct_premium_case(telegram_id: int):
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "premium_cases": user["premium_cases"] - 1
    }).eq("telegram_id", telegram_id).execute()


# ── Inventory ─────────────────────────────────────────────────────────

def get_inventory(telegram_id: int) -> list:
    res = supabase.table("inventory") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .eq("status", "active") \
        .order("obtained_at", desc=True) \
        .limit(50) \
        .execute()
    return res.data or []


def sell_item(inventory_id: int, telegram_id: int) -> int:
    """Itemni sotadi, qiymatini qaytaradi"""
    item = supabase.table("inventory").select("*").eq("id", inventory_id).single().execute().data
    if not item or item["telegram_id"] != telegram_id or item["status"] != "active":
        return 0
    supabase.table("inventory").update({"status": "sold"}).eq("id", inventory_id).execute()
    # Stars balansiga qo'shish (value / 10 stars, siz o'zgartira olasiz)
    reward = max(1, item["prize_value"] // 10)
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "stars_balance": user["stars_balance"] + reward
    }).eq("telegram_id", telegram_id).execute()
    return reward


# ── Withdraw ──────────────────────────────────────────────────────────

def create_withdraw_request(telegram_id: int, inventory_id: int) -> dict | None:
    item = supabase.table("inventory").select("*").eq("id", inventory_id).single().execute().data
    if not item or item["telegram_id"] != telegram_id or item["status"] != "active":
        return None
    user = get_or_create_user(telegram_id)
    if not user.get("steam_trade_url"):
        return None

    # statusni pending ga o'tkazish
    supabase.table("inventory").update({"status": "withdraw_pending"}).eq("id", inventory_id).execute()

    req = {
        "telegram_id":    telegram_id,
        "inventory_id":   inventory_id,
        "prize_name":     item["prize_name"],
        "prize_image":    item.get("prize_image", ""),
        "steam_trade_url": user["steam_trade_url"],
        "status":         "pending",
    }
    res = supabase.table("withdraw_requests").insert(req).execute()
    return res.data[0]


# ── Payments ──────────────────────────────────────────────────────────

def save_payment(telegram_id: int, stars: int, cases: int, charge_id: str):
    supabase.table("payments").insert({
        "telegram_id":        telegram_id,
        "stars_amount":       stars,
        "cases_granted":      cases,
        "telegram_charge_id": charge_id,
    }).execute()
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "premium_cases": user["premium_cases"] + cases,
        "stars_balance": user["stars_balance"] + stars,
    }).eq("telegram_id", telegram_id).execute()


# ── Tasks ─────────────────────────────────────────────────────────────

def get_completed_tasks(telegram_id: int) -> set:
    res = supabase.table("tasks_completed").select("task_key").eq("telegram_id", telegram_id).execute()
    return {r["task_key"] for r in (res.data or [])}


def complete_task(telegram_id: int, task_key: str, reward_cases: int):
    supabase.table("tasks_completed").insert({
        "telegram_id":   telegram_id,
        "task_key":      task_key,
        "reward_cases":  reward_cases,
    }).execute()
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "premium_cases": user["premium_cases"] + reward_cases
    }).eq("telegram_id", telegram_id).execute()


# ── Leaderboard ───────────────────────────────────────────────────────

def get_leaderboard() -> list:
    res = supabase.rpc("get_leaderboard").execute()
    if res.data:
        return res.data
    # fallback — oddiy query
    res = supabase.table("case_openings") \
        .select("telegram_id, users(username, first_name)") \
        .execute()
    # Supabase RPC yo'q bo'lsa manual hisoblash
    counts: dict = {}
    for row in (res.data or []):
        tid = row["telegram_id"]
        counts[tid] = counts.get(tid, {"wins": 0, "totalValue": 0, "username": ""})
        counts[tid]["wins"] += 1
    return sorted(counts.values(), key=lambda x: x["totalValue"], reverse=True)[:10]
