from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timezone, timedelta

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Users ─────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    try:
        res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
        if res.data:
            row = res.data[0]
            # Username yangilanishi
            if username and row.get("username") != username:
                supabase.table("users").update({
                    "username": username,
                    "first_name": first_name
                }).eq("telegram_id", telegram_id).execute()
            return supabase.table("users").select("*").eq("telegram_id", telegram_id).execute().data[0]
    except Exception:
        pass

    # Yangi user yaratish
    data = {
        "telegram_id": telegram_id,
        "username":    username,
        "first_name":  first_name,
        "stars_balance": 0,
        "premium_cases": 0,
    }
    supabase.table("users").insert(data).execute()
    return supabase.table("users").select("*").eq("telegram_id", telegram_id).execute().data[0]


def set_steam_url(telegram_id: int, url: str):
    supabase.table("users").update({"steam_trade_url": url}).eq("telegram_id", telegram_id).execute()


# ── Case openings ─────────────────────────────────────────────────────

def save_opening(telegram_id: int, case_id: str, prize: dict, was_free: bool) -> dict:
    # case_openings ga yozish
    supabase.table("case_openings").insert({
        "telegram_id":  telegram_id,
        "case_id":      case_id,
        "prize_name":   prize["name"],
        "prize_image":  prize.get("image", ""),
        "prize_value":  prize["value"],
        "prize_rarity": prize["rarity"],
        "was_free":     was_free,
    }).execute()

    # Inventarga qo'shish
    inv = supabase.table("inventory").insert({
        "telegram_id":  telegram_id,
        "prize_name":   prize["name"],
        "prize_image":  prize.get("image", ""),
        "prize_value":  prize["value"],
        "prize_rarity": prize["rarity"],
        "status":       "active",
    }).execute()

    return inv.data[0] if inv.data else {"id": 0}


def update_free_case_time(telegram_id: int):
    supabase.table("users").update({
        "free_case_used_at": datetime.now(timezone.utc).isoformat()
    }).eq("telegram_id", telegram_id).execute()


def deduct_premium_case(telegram_id: int):
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "premium_cases": max(0, user["premium_cases"] - 1)
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
    res = supabase.table("inventory").select("*").eq("id", inventory_id).execute()
    if not res.data:
        return 0
    item = res.data[0]
    if item["telegram_id"] != telegram_id or item["status"] != "active":
        return 0

    supabase.table("inventory").update({"status": "sold"}).eq("id", inventory_id).execute()
    reward = max(1, item["prize_value"] // 10)
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "stars_balance": user["stars_balance"] + reward
    }).eq("telegram_id", telegram_id).execute()
    return reward


# ── Withdraw ──────────────────────────────────────────────────────────

def create_withdraw_request(telegram_id: int, inventory_id: int) -> dict | None:
    inv_res = supabase.table("inventory").select("*").eq("id", inventory_id).execute()
    if not inv_res.data:
        return None
    item = inv_res.data[0]
    if item["telegram_id"] != telegram_id or item["status"] != "active":
        return None

    user_res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if not user_res.data or not user_res.data[0].get("steam_trade_url"):
        return None
    user = user_res.data[0]

    supabase.table("inventory").update({"status": "withdraw_pending"}).eq("id", inventory_id).execute()

    req = supabase.table("withdraw_requests").insert({
        "telegram_id":     telegram_id,
        "inventory_id":    inventory_id,
        "prize_name":      item["prize_name"],
        "prize_image":     item.get("prize_image", ""),
        "steam_trade_url": user["steam_trade_url"],
        "status":          "pending",
    }).execute()

    return req.data[0] if req.data else None


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
    res = supabase.table("tasks_completed") \
        .select("task_key") \
        .eq("telegram_id", telegram_id) \
        .execute()
    return {r["task_key"] for r in (res.data or [])}


def complete_task(telegram_id: int, task_key: str, reward_cases: int):
    supabase.table("tasks_completed").insert({
        "telegram_id":  telegram_id,
        "task_key":     task_key,
        "reward_cases": reward_cases,
    }).execute()
    user = get_or_create_user(telegram_id)
    supabase.table("users").update({
        "premium_cases": user["premium_cases"] + reward_cases
    }).eq("telegram_id", telegram_id).execute()


# ── Leaderboard ───────────────────────────────────────────────────────

def get_leaderboard() -> list:
    try:
        res = supabase.table("case_openings") \
            .select("telegram_id, prize_value, users(username, first_name)") \
            .execute()

        counts: dict = {}
        for row in (res.data or []):
            tid = row["telegram_id"]
            if tid not in counts:
                u = row.get("users") or {}
                counts[tid] = {
                    "telegramId": tid,
                    "username":   u.get("username", ""),
                    "totalValue": 0,
                    "wins":       0,
                }
            counts[tid]["totalValue"] += row["prize_value"]
            counts[tid]["wins"]       += 1

        return sorted(counts.values(), key=lambda x: x["totalValue"], reverse=True)[:10]
    except Exception:
        return []