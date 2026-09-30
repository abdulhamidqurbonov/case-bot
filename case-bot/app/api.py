import hmac
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import BOT_TOKEN, ADMIN_CHAT_ID, FREE_CASE_COOLDOWN_H
from app.database import (
    get_or_create_user, save_opening, update_free_case_time,
    get_inventory, sell_item, create_withdraw_request,
    get_completed_tasks, complete_task, get_leaderboard,
    save_payment, set_steam_url, get_conn,
)
from app.prizes import pick_prize, get_case, CASES, PACKAGES

router = APIRouter()


def verify_init_data(init_data: str):
    try:
        params   = {k: v[0] for k, v in parse_qs(init_data, keep_blank_values=True).items()}
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


class Body(BaseModel):
    initData: str = ""


def auth(init_data: str):
    user = verify_init_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_init_data")
    return user


# ── /api/me ───────────────────────────────────────────────────────────
@router.post("/api/me")
async def api_me(body: Body):
    user    = auth(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))

    free_available = True
    seconds_left   = 0
    raw = db_user.get("free_case_used_at")
    if raw:
        used_dt   = raw if hasattr(raw, "tzinfo") else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if used_dt.tzinfo is None:
            used_dt = used_dt.replace(tzinfo=timezone.utc)
        next_free = used_dt + timedelta(hours=FREE_CASE_COOLDOWN_H)
        now       = datetime.now(timezone.utc)
        if now < next_free:
            free_available = False
            seconds_left   = int((next_free - now).total_seconds())

    return {
        "telegramId":      db_user["telegram_id"],
        "username":        db_user.get("username"),
        "firstName":       db_user.get("first_name"),
        "starsBalance":    db_user["stars_balance"],
        "premiumCases":    db_user["premium_cases"],
        "freeAvailable":   free_available,
        "freeSecondsLeft": seconds_left,
        "steamUrl":        db_user.get("steam_trade_url") or "",
    }


# ── /api/cases ────────────────────────────────────────────────────────
@router.get("/api/cases")
async def api_cases():
    return {"cases": CASES}


# ── /api/open-case ────────────────────────────────────────────────────
class OpenBody(BaseModel):
    initData: str = ""
    caseId:   str = "free"
    qty:      int = 1


@router.post("/api/open-case")
async def api_open_case(body: OpenBody):
    user    = auth(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))
    case    = get_case(body.caseId)
    if not case:
        raise HTTPException(status_code=400, detail="unknown_case")

    qty     = max(1, min(body.qty, 10))
    is_free = (case["price"] == 0)

    if is_free:
        raw = db_user.get("free_case_used_at")
        if raw:
            used_dt = raw if hasattr(raw, "tzinfo") else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if used_dt.tzinfo is None:
                used_dt = used_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < used_dt + timedelta(hours=FREE_CASE_COOLDOWN_H):
                raise HTTPException(status_code=400, detail="free_case_cooldown")
        prize    = pick_prize(body.caseId)
        inv_item = save_opening(user["id"], body.caseId, prize, was_free=True)
        update_free_case_time(user["id"])
        return {"results": [{**prize, "inventoryId": inv_item["id"]}], "wasFree": True}

    cost = case["price"] * qty
    if db_user["stars_balance"] < cost:
        raise HTTPException(status_code=400, detail="insufficient_stars")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET stars_balance = stars_balance - %s WHERE telegram_id = %s",
                (cost, user["id"])
            )
        conn.commit()
    finally:
        conn.close()

    results = []
    for _ in range(qty):
        prize    = pick_prize(body.caseId)
        inv_item = save_opening(user["id"], body.caseId, prize, was_free=False)
        results.append({**prize, "inventoryId": inv_item["id"]})

    return {"results": results, "wasFree": False, "totalCost": cost}


# ── /api/inventory ────────────────────────────────────────────────────
@router.post("/api/inventory")
async def api_inventory(body: Body):
    user = auth(body.initData)
    return {"items": get_inventory(user["id"])}


# ── /api/sell ─────────────────────────────────────────────────────────
class SellBody(BaseModel):
    initData:    str = ""
    inventoryId: int = 0


@router.post("/api/sell")
async def api_sell(body: SellBody):
    user   = auth(body.initData)
    reward = sell_item(body.inventoryId, user["id"])
    if reward == 0:
        raise HTTPException(status_code=400, detail="item_not_found")
    return {"reward": reward, "message": "+" + str(reward) + " Stars balansga qoshildi"}


# ── /api/withdraw ─────────────────────────────────────────────────────
class WithdrawBody(BaseModel):
    initData:    str = ""
    inventoryId: int = 0


@router.post("/api/withdraw")
async def api_withdraw(body: WithdrawBody):
    user    = auth(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"))

    if not db_user.get("steam_trade_url"):
        raise HTTPException(status_code=400, detail="no_steam_url")

    req = create_withdraw_request(user["id"], body.inventoryId)
    if not req:
        raise HTTPException(status_code=400, detail="withdraw_failed")

    try:
        from app.bot import bot_instance
        if bot_instance and ADMIN_CHAT_ID:
            req_id    = str(req["id"])
            uname     = user.get("username") or "Noma'lum"
            prize_n   = req["prize_name"]
            trade_url = req["steam_trade_url"]
            msg = (
                "\U0001f4e6 <b>Yangi chiqarish sorovi #" + req_id + "</b>\n\n"
                + "\U0001f464 @" + uname + "\n"
                + "\U0001f52b Skin: <b>" + prize_n + "</b>\n"
                + "\U0001f517 Trade URL:\n<code>" + trade_url + "</code>\n\n"
                + "Yuborgach: /confirm_" + req_id
            )
            await bot_instance.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except Exception:
        pass

    return {"success": True, "requestId": req["id"]}


# ── /api/set-steam ────────────────────────────────────────────────────
class SteamBody(BaseModel):
    initData: str = ""
    url:      str = ""


@router.post("/api/set-steam")
async def api_set_steam(body: SteamBody):
    user = auth(body.initData)
    if "steamcommunity.com/tradeoffer" not in body.url:
        raise HTTPException(status_code=400, detail="invalid_url")
    set_steam_url(user["id"], body.url)
    return {"success": True}


# ── /api/tasks ────────────────────────────────────────────────────────
@router.post("/api/tasks")
async def api_tasks(body: Body):
    user      = auth(body.initData)
    completed = get_completed_tasks(user["id"])
    channel   = os.getenv("CHANNEL_USERNAME", "")
    tasks     = []
    if channel:
        tasks.append({
            "id":        "join_channel",
            "title":     "Kanalga obuna bo'ling",
            "subtitle":  channel,
            "reward":    1,
            "completed": "join_channel" in completed,
            "channel":   channel,
        })
    return {"tasks": tasks}


# ── /api/tasks/check ─────────────────────────────────────────────────
class TaskBody(BaseModel):
    initData: str = ""
    taskId:   str = ""


@router.post("/api/tasks/check")
async def api_task_check(body: TaskBody):
    user      = auth(body.initData)
    completed = get_completed_tasks(user["id"])
    if body.taskId in completed:
        raise HTTPException(status_code=400, detail="already_completed")
    if body.taskId == "join_channel":
        channel = os.getenv("CHANNEL_USERNAME", "")
        if not channel:
            raise HTTPException(status_code=400, detail="no_channel")
        try:
            from app.bot import bot_instance
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
    return {"leaderboard": get_leaderboard()}


# ── /api/profile ─────────────────────────────────────────────────────
@router.post("/api/profile")
async def api_profile(body: Body):
    user    = auth(body.initData)
    db_user = get_or_create_user(user["id"], user.get("username"), user.get("first_name"))

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as wins, COALESCE(SUM(prize_value),0) as total_value"
                " FROM case_openings WHERE telegram_id=%s",
                (user["id"],)
            )
            stats = dict(cur.fetchone())
            cur.execute(
                "SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id=%s",
                (user["id"],)
            )
            refs = cur.fetchone()["cnt"]
    finally:
        conn.close()

    created = db_user.get("created_at")
    try:
        if isinstance(created, str):
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            created_dt = created
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        days = max(1, (datetime.now(timezone.utc) - created_dt).days + 1)
    except Exception:
        days = 1

    return {
        "username":     db_user.get("username"),
        "firstName":    db_user.get("first_name"),
        "starsBalance": db_user["stars_balance"],
        "premiumCases": db_user["premium_cases"],
        "wins":         stats["wins"],
        "totalValue":   stats["total_value"],
        "referrals":    refs,
        "daysWithUs":   days,
        "steamUrl":     db_user.get("steam_trade_url") or "",
    }


# ── /api/create-invoice ───────────────────────────────────────────────
class InvoiceBody(BaseModel):
    initData: str = ""
    package:  str = ""


@router.post("/api/create-invoice")
async def api_create_invoice(body: InvoiceBody):
    user = auth(body.initData)
    pkg  = PACKAGES.get(body.package)
    if not pkg:
        raise HTTPException(status_code=400, detail="unknown_package")
    try:
        from app.bot import bot_instance
        link = await bot_instance.create_invoice_link(
            title=pkg["label"],
            description=str(pkg["cases"]) + " ta Premium Case oching",
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
async def api_referral(body: Body):
    user   = auth(body.initData)
    bot_un = os.getenv("BOT_USERNAME", "")
    link   = ("https://t.me/" + bot_un + "?start=ref_" + str(user["id"])) if bot_un else ""

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id=%s", (user["id"],))
            count = cur.fetchone()["cnt"]
    finally:
        conn.close()

    return {"link": link, "referralCount": count}