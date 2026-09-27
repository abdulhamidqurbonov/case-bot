import hmac
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs
from functools import wraps

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import BOT_TOKEN, ADMIN_CHAT_ID, FREE_CASE_COOLDOWN_H, MIN_WITHDRAW_STARS
from app.database import (
    get_or_create_user, save_opening, update_free_case_time,
    deduct_premium_case, get_inventory, sell_item,
    create_withdraw_request, get_completed_tasks, complete_task,
    get_leaderboard, supabase
)
from app.prizes import pick_prize, get_case, CASES, PACKAGES

router = APIRouter()


# ── initData tekshirish ───────────────────────────────────────────────
def verify_init_data(init_data: str) -> dict | None:
    try:
        params = dict(parse_qs(init_data, keep_blank_values=True))
        params = {k: v[0] for k, v in params.items()}
        received = params.pop("hash", None)
        if not received:
            return None
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret    = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed  = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
        if computed != received:
            return None
        return json.loads(params.get("user", "{}"))
    except Exception:
        return None


class InitDataBody(BaseModel):
    initData: str = ""


def get_user_or_401(init_data: str):
    user = verify_init_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_init_data")
    return user


# ── /api/me ───────────────────────────────────────────────────────────
@router.post("/api/me")
async def api_me(body: InitDataBody):
    user    = get_user_or_401(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))

    # Bepul case holati
    free_used_at  = db_user.get("free_case_used_at")
    free_available = True
    seconds_left   = 0
    if free_used_at:
        if isinstance(free_used_at, str):
            used_dt = datetime.fromisoformat(free_used_at.replace("Z", "+00:00"))
        else:
            used_dt = free_used_at
        next_free = used_dt + timedelta(hours=FREE_CASE_COOLDOWN_H)
        now       = datetime.now(timezone.utc)
        if now < next_free:
            free_available = False
            seconds_left   = int((next_free - now).total_seconds())

    return {
        "telegramId":     db_user["telegram_id"],
        "username":       db_user.get("username"),
        "firstName":      db_user.get("first_name"),
        "starsBalance":   db_user["stars_balance"],
        "premiumCases":   db_user["premium_cases"],
        "freeAvailable":  free_available,
        "freeSecondsLeft": seconds_left,
        "steamUrl":       db_user.get("steam_trade_url", ""),
    }


# ── /api/cases ────────────────────────────────────────────────────────
@router.get("/api/cases")
async def api_cases():
    return {"cases": CASES}


# ── /api/open-case ────────────────────────────────────────────────────
class OpenCaseBody(BaseModel):
    initData: str = ""
    caseId:   str = "free"
    qty:      int = 1


@router.post("/api/open-case")
async def api_open_case(body: OpenCaseBody):
    user    = get_user_or_401(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))
    case    = get_case(body.caseId)

    if not case:
        raise HTTPException(status_code=400, detail="unknown_case")

    qty     = max(1, min(body.qty, 10))
    is_free = (case["price"] == 0)
    results = []

    # ── Bepul case ──
    if is_free:
        free_used_at = db_user.get("free_case_used_at")
        if free_used_at:
            if isinstance(free_used_at, str):
                used_dt = datetime.fromisoformat(free_used_at.replace("Z", "+00:00"))
            else:
                used_dt = free_used_at
            next_free = used_dt + timedelta(hours=FREE_CASE_COOLDOWN_H)
            if datetime.now(timezone.utc) < next_free:
                raise HTTPException(status_code=400, detail="free_case_cooldown")
        prize    = pick_prize(body.caseId)
        inv_item = save_opening(user["id"], body.caseId, prize, was_free=True)
        update_free_case_time(user["id"])
        return {"results": [{**prize, "inventoryId": inv_item["id"]}], "wasFree": True}

    # ── Premium case (Stars bilan) ──
    cost = case["price"] * qty
    if db_user["stars_balance"] < cost:
        raise HTTPException(status_code=400, detail="insufficient_stars")

    # Balansdan ayirish
    supabase.table("users").update({
        "stars_balance": db_user["stars_balance"] - cost
    }).eq("telegram_id", user["id"]).execute()

    for _ in range(qty):
        prize    = pick_prize(body.caseId)
        inv_item = save_opening(user["id"], body.caseId, prize, was_free=False)
        results.append({**prize, "inventoryId": inv_item["id"]})

    return {"results": results, "wasFree": False, "totalCost": cost}


# ── /api/inventory ────────────────────────────────────────────────────
@router.post("/api/inventory")
async def api_inventory(body: InitDataBody):
    user  = get_user_or_401(body.initData)
    items = get_inventory(user["id"])
    return {"items": items}


# ── /api/sell ────────────────────────────────────────────────────────
class SellBody(BaseModel):
    initData:    str = ""
    inventoryId: int = 0


@router.post("/api/sell")
async def api_sell(body: SellBody):
    user   = get_user_or_401(body.initData)
    reward = sell_item(body.inventoryId, user["id"])
    if reward == 0:
        raise HTTPException(status_code=400, detail="item_not_found")
    return {"reward": reward, "message": f"+{reward} Stars balansga qo'shildi"}


# ── /api/withdraw ─────────────────────────────────────────────────────
class WithdrawBody(BaseModel):
    initData:    str = ""
    inventoryId: int = 0


@router.post("/api/withdraw")
async def api_withdraw(body: WithdrawBody):
    user    = get_user_or_401(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"))

    # Steam URL bormi?
    if not db_user.get("steam_trade_url"):
        raise HTTPException(status_code=400, detail="no_steam_url")

    # Minimum to'lov tekshirish
    # (Ixtiyoriy — o'chirib tashlashingiz mumkin)
    # total_spent = db_user["stars_balance"]
    # if total_spent < MIN_WITHDRAW_STARS:
    #     raise HTTPException(status_code=400, detail="min_payment_required")

    req = create_withdraw_request(user["id"], body.inventoryId)
    if not req:
        raise HTTPException(status_code=400, detail="withdraw_failed")

    # Adminga xabar yuborish
    try:
        from app.bot import admin_withdraw_notify
        import asyncio
        asyncio.create_task(
            admin_withdraw_notify(
                req["prize_name"],
                req["steam_trade_url"],
                user.get("username", ""),
                req["id"]
            )
        )
    except Exception:
        pass

    return {"success": True, "requestId": req["id"]}


# ── /api/set-steam ────────────────────────────────────────────────────
class SteamBody(BaseModel):
    initData: str = ""
    url:      str = ""


@router.post("/api/set-steam")
async def api_set_steam(body: SteamBody):
    user = get_user_or_401(body.initData)
    if "steamcommunity.com/tradeoffer" not in body.url:
        raise HTTPException(status_code=400, detail="invalid_url")
    from app.database import set_steam_url
    set_steam_url(user["id"], body.url)
    return {"success": True}


# ── /api/tasks ────────────────────────────────────────────────────────
TASKS_LIST = [
    {
        "id":       "join_channel",
        "title":    "Kanalga obuna bo'ling",
        "reward":   1,
        "channel":  "",   # .env dan CHANNEL_USERNAME o'qiladi
    },
    {
        "id":       "invite_friend",
        "title":    "Do'st taklif qiling",
        "reward":   2,
        "channel":  None,
    },
]


@router.post("/api/tasks")
async def api_tasks(body: InitDataBody):
    import os
    user      = get_user_or_401(body.initData)
    completed = get_completed_tasks(user["id"])
    channel   = os.getenv("CHANNEL_USERNAME", "")

    tasks = []
    for t in TASKS_LIST:
        if t["id"] == "join_channel" and not channel:
            continue
        tasks.append({
            **t,
            "channel":   channel if t["id"] == "join_channel" else t.get("channel"),
            "completed": t["id"] in completed,
        })
    return {"tasks": tasks}


# ── /api/tasks/check ─────────────────────────────────────────────────
class TaskCheckBody(BaseModel):
    initData: str = ""
    taskId:   str = ""


@router.post("/api/tasks/check")
async def api_task_check(body: TaskCheckBody):
    import os
    from app.bot import bot_instance
    user      = get_user_or_401(body.initData)
    completed = get_completed_tasks(user["id"])

    if body.taskId in completed:
        raise HTTPException(status_code=400, detail="already_completed")

    if body.taskId == "join_channel":
        channel = os.getenv("CHANNEL_USERNAME", "")
        if not channel:
            raise HTTPException(status_code=400, detail="no_channel")
        try:
            member = await bot_instance.get_chat_member(channel, user["id"])
            if member.status not in ("member", "administrator", "creator"):
                raise HTTPException(status_code=400, detail="not_member")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="check_failed")
        complete_task(user["id"], "join_channel", 1)
        return {"success": True, "reward": 1}

    raise HTTPException(status_code=400, detail="unknown_task")


# ── /api/leaderboard ─────────────────────────────────────────────────
@router.get("/api/leaderboard")
async def api_leaderboard():
    rows = get_leaderboard()
    return {"leaderboard": rows}


# ── /api/profile ─────────────────────────────────────────────────────
@router.post("/api/profile")
async def api_profile(body: InitDataBody):
    user    = get_user_or_401(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))

    stats = supabase.table("case_openings") \
        .select("prize_value") \
        .eq("telegram_id", user["id"]) \
        .execute()
    wins       = len(stats.data or [])
    total_val  = sum(r["prize_value"] for r in (stats.data or []))

    refs = supabase.table("referrals").select("id").eq("referrer_id", user["id"]).execute()

    created = db_user.get("created_at", "")
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        days = max(1, (datetime.now(timezone.utc) - created_dt).days + 1)
    except Exception:
        days = 1

    return {
        "username":   db_user.get("username"),
        "firstName":  db_user.get("first_name"),
        "starsBalance": db_user["stars_balance"],
        "premiumCases": db_user["premium_cases"],
        "wins":       wins,
        "totalValue": total_val,
        "referrals":  len(refs.data or []),
        "daysWithUs": days,
        "steamUrl":   db_user.get("steam_trade_url", ""),
    }


# ── /api/create-invoice ───────────────────────────────────────────────
class InvoiceBody(BaseModel):
    initData: str = ""
    package:  str = ""


@router.post("/api/create-invoice")
async def api_create_invoice(body: InvoiceBody):
    from app.bot import bot_instance
    user = get_user_or_401(body.initData)
    pkg  = PACKAGES.get(body.package)
    if not pkg:
        raise HTTPException(status_code=400, detail="unknown_package")
    try:
        link = await bot_instance.create_invoice_link(
            title=pkg["label"],
            description=f"{pkg['cases']} ta Premium Case oching",
            payload=json.dumps({"telegramId": user["id"], "package": body.package}),
            provider_token="",
            currency="XTR",
            prices=[{"label": pkg["label"], "amount": pkg["stars"]}],
        )
        return {"invoiceLink": link}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /api/referral ─────────────────────────────────────────────────────
@router.post("/api/referral")
async def api_referral(body: InitDataBody):
    import os
    user    = get_user_or_401(body.initData)
    bot_un  = os.getenv("BOT_USERNAME", "")
    link    = f"https://t.me/{bot_un}?start=ref_{user['id']}" if bot_un else ""
    refs    = supabase.table("referrals").select("id").eq("referrer_id", user["id"]).execute()
    return {"link": link, "referralCount": len(refs.data or [])}
