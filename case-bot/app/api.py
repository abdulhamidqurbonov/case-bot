"""WebApp uchun API. Har bir so'rov Telegram initData imzosi bilan tekshiriladi.

Eslatma: DB bilan ishlaydigan oddiy endpointlar `def` (async emas) — FastAPI ularni
alohida thread'da bajaradi va server bloklanmaydi.
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl, urlparse, parse_qs

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import database as dbm
from app.config import (
    ADMIN_CHAT_ID, BOT_TOKEN, BOT_USERNAME, CHANNEL_USERNAME,
    FREE_CASE_COOLDOWN_H, INIT_DATA_MAX_AGE_S, TASK_BONUS_STARS,
)
from app.prizes import CASES, PACKAGES, get_case, pick_prize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ── Autentifikatsiya ──────────────────────────────────────────────────

def verify_init_data(init_data: str) -> dict | None:
    """Telegram WebApp initData imzosini va muddatini tekshiradi."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = params.pop("hash", None)
    if not received:
        return None

    check_str = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received):
        return None

    try:
        auth_date = int(params.get("auth_date", "0"))
    except ValueError:
        return None
    if INIT_DATA_MAX_AGE_S > 0 and time.time() - auth_date > INIT_DATA_MAX_AGE_S:
        return None

    try:
        user = json.loads(params.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return user


def auth(init_data: str) -> dict:
    user = verify_init_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="invalid_init_data")
    return user


def game_call(fn, *args):
    """GameError'ni 400 javobga aylantiradi."""
    try:
        return fn(*args)
    except dbm.GameError as e:
        raise HTTPException(status_code=400, detail=e.code)


def _bot():
    from app.bot import get_bot
    return get_bot()


# ── So'rov modellari ──────────────────────────────────────────────────

class Body(BaseModel):
    initData: str = ""


class OpenBody(Body):
    caseId: str = "free"
    qty: int = Field(default=1, ge=1, le=10)


class ItemBody(Body):
    inventoryId: int = 0


class SteamBody(Body):
    url: str = ""


class TaskBody(Body):
    taskId: str = ""


class InvoiceBody(Body):
    package: str = ""


# ── Endpointlar ───────────────────────────────────────────────────────

@router.post("/me")
def api_me(body: Body):
    user = auth(body.initData)
    u = dbm.get_me(user["id"], user.get("username"), user.get("first_name"), FREE_CASE_COOLDOWN_H)
    return {
        "telegramId":      u["telegram_id"],
        "username":        u.get("username"),
        "firstName":       u.get("first_name"),
        "starsBalance":    u["stars_balance"],
        "premiumCases":    u.get("premium_cases") or 0,
        "freeAvailable":   u["free_seconds_left"] == 0,
        "freeSecondsLeft": u["free_seconds_left"],
        "steamUrl":        u.get("steam_trade_url") or "",
    }


@router.get("/cases")
def api_cases():
    return {"cases": CASES}


@router.get("/packages")
def api_packages():
    return {"packages": [
        {"id": key, "stars": p["stars"], "bonus": p["bonus"], "label": p["label"]}
        for key, p in PACKAGES.items()
    ]}


@router.post("/open-case")
def api_open_case(body: OpenBody):
    user = auth(body.initData)
    case = get_case(body.caseId)
    if not case:
        raise HTTPException(status_code=400, detail="unknown_case")
    dbm.get_or_create_user(user["id"], user.get("username"), user.get("first_name"))
    return game_call(dbm.open_case, user["id"], case, body.qty, FREE_CASE_COOLDOWN_H, pick_prize)


@router.post("/inventory")
def api_inventory(body: Body):
    user = auth(body.initData)
    return {"items": dbm.get_inventory(user["id"])}


@router.post("/sell")
def api_sell(body: ItemBody):
    user = auth(body.initData)
    res = game_call(dbm.sell_item, user["id"], body.inventoryId)
    return {**res, "message": f"+{res['reward']} Stars balansga qo'shildi"}


@router.post("/withdraw")
async def api_withdraw(body: ItemBody):
    user = auth(body.initData)
    req = await run_in_threadpool(game_call, dbm.create_withdraw_request, user["id"], body.inventoryId)

    if ADMIN_CHAT_ID:
        uname = ("@" + user["username"]) if user.get("username") else f"id {user['id']}"
        msg = (
            f"📦 <b>Yangi chiqarish so'rovi #{req['id']}</b>\n\n"
            f"👤 {uname}\n"
            f"🔫 Skin: <b>{_esc(req['prize_name'])}</b>\n"
            f"🔗 Trade URL:\n<code>{_esc(req['steam_trade_url'])}</code>\n\n"
            f"Yuborgach: /confirm_{req['id']}\n"
            f"Rad etish: /reject_{req['id']}"
        )
        try:
            await _bot().send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
        except Exception:
            logger.exception("Adminga withdraw xabari yuborilmadi")

    return {"success": True, "requestId": req["id"]}


def _valid_trade_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    q = parse_qs(p.query)
    return (
        p.scheme == "https"
        and p.netloc == "steamcommunity.com"
        and p.path.rstrip("/") == "/tradeoffer/new"
        and "partner" in q and "token" in q
    )


@router.post("/set-steam")
def api_set_steam(body: SteamBody):
    user = auth(body.initData)
    if len(body.url) > 300 or not _valid_trade_url(body.url):
        raise HTTPException(status_code=400, detail="invalid_url")
    dbm.set_steam_url(user["id"], body.url.strip())
    return {"success": True}


@router.post("/tasks")
def api_tasks(body: Body):
    user = auth(body.initData)
    completed = dbm.get_completed_tasks(user["id"])
    tasks = []
    if CHANNEL_USERNAME:
        tasks.append({
            "id":        "join_channel",
            "title":     "Kanalga obuna bo'ling",
            "subtitle":  CHANNEL_USERNAME,
            "reward":    TASK_BONUS_STARS,
            "completed": "join_channel" in completed,
            "channel":   CHANNEL_USERNAME,
        })
    return {"tasks": tasks}


@router.post("/tasks/check")
async def api_task_check(body: TaskBody):
    user = auth(body.initData)
    if body.taskId != "join_channel" or not CHANNEL_USERNAME:
        raise HTTPException(status_code=400, detail="unknown_task")

    try:
        member = await _bot().get_chat_member(CHANNEL_USERNAME, user["id"])
    except Exception:
        logger.exception("Obunani tekshirib bo'lmadi (bot kanalda admin ekanini tekshiring)")
        raise HTTPException(status_code=500, detail="check_failed")
    if member.status not in ("member", "administrator", "creator"):
        raise HTTPException(status_code=400, detail="not_member")

    balance = await run_in_threadpool(
        game_call, dbm.complete_task, user["id"], "join_channel", TASK_BONUS_STARS)
    return {"success": True, "reward": TASK_BONUS_STARS, "balance": balance}


@router.get("/leaderboard")
def api_leaderboard():
    return {"leaderboard": dbm.get_leaderboard()}


@router.post("/profile")
def api_profile(body: Body):
    user = auth(body.initData)
    p = dbm.get_profile(user["id"], user.get("username"), user.get("first_name"))
    return {
        "username":     p.get("username"),
        "firstName":    p.get("first_name"),
        "starsBalance": p["stars_balance"],
        "premiumCases": p.get("premium_cases") or 0,
        "wins":         p["wins"],
        "totalValue":   p["total_value"],
        "referrals":    p["referrals"],
        "daysWithUs":   p["days"],
        "steamUrl":     p.get("steam_trade_url") or "",
    }


@router.post("/create-invoice")
async def api_create_invoice(body: InvoiceBody):
    user = auth(body.initData)
    pkg = PACKAGES.get(body.package)
    if not pkg:
        raise HTTPException(status_code=400, detail="unknown_package")

    total = pkg["stars"] + pkg["bonus"]
    try:
        link = await _bot().create_invoice_link(
            title=pkg["label"],
            description=f"Balansingizga {total} Stars qo'shiladi",
            payload=json.dumps({"u": user["id"], "p": body.package}),
            provider_token="",
            currency="XTR",
            prices=[{"label": pkg["label"], "amount": pkg["stars"]}],
        )
    except Exception:
        logger.exception("Invoice yaratilmadi")
        raise HTTPException(status_code=500, detail="invoice_failed")
    return {"invoiceLink": link}


@router.post("/referral")
def api_referral(body: Body):
    user = auth(body.initData)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['id']}" if BOT_USERNAME else ""
    return {"link": link, "referralCount": dbm.referral_count(user["id"])}


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
