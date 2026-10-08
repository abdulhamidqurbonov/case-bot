"""WebApp uchun API. Har bir so'rov Telegram initData imzosi bilan tekshiriladi.

Eslatma: DB bilan ishlaydigan oddiy endpointlar `def` (async emas) — FastAPI ularni
alohida thread'da bajaradi va server bloklanmaydi.
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import catalog, games, media, steam
from app import database as dbm
from app.config import (
    ADMIN_CHAT_ID, BOT_TOKEN, BOT_USERNAME, CHANNEL_USERNAME, CONTRACT_RTP_PERCENT,
    CRASH_RTP_PERCENT, DICE_RTP_PERCENT, FREE_CASE_COOLDOWN_H, INIT_DATA_MAX_AGE_S,
    MAX_BET, MAX_WIN, MIN_BET, MIN_WITHDRAW_VALUE, REFERRAL_BONUS_STARS, SELL_RATE_PERCENT, TASK_BONUS_STARS,
    UPGRADE_RTP_PERCENT, WITHDRAW_NEEDS_DEPOSIT,
)

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
    caseId: str
    qty: int = Field(default=1, ge=1, le=5)


class ItemBody(Body):
    inventoryId: int


class ItemsBody(Body):
    ids: list[int] = Field(default_factory=list, max_length=500)
    all: bool = False


class SteamBody(Body):
    url: str = ""


class TaskBody(Body):
    taskId: str = ""


class InvoiceBody(Body):
    package: str = ""


class UpgradeBody(Body):
    inventoryId: int
    targetKey: str


class ContractBody(Body):
    ids: list[int] = Field(min_length=1, max_length=20)


class CrashBody(Body):
    bet: int
    target: float


class DiceBody(Body):
    bet: int
    chance: float
    over: bool = False


# ── Yordamchilar ──────────────────────────────────────────────────────

_LEGACY_RARITY = {"common": "consumer", "uncommon": "milspec", "rare": "restricted",
                  "epic": "classified", "legendary": "covert"}


def item_out(row: dict) -> dict:
    """Inventar qatorini frontend formatiga o'giradi."""
    key = row.get("skin_key") or catalog.key_by_name(row.get("prize_name"))
    return {
        "id": row["id"],
        "key": key,
        "name": row["prize_name"],
        "value": row["prize_value"],
        "rarity": _rarity(row["prize_rarity"]),
        "sell": max(1, row["prize_value"] * SELL_RATE_PERCENT // 100),
    }


def _rarity(r: str) -> str:
    if r in catalog.RARITIES:
        return r
    return _LEGACY_RARITY.get(r, "consumer")


def me_out(u: dict) -> dict:
    return {
        "id":              u["telegram_id"],
        "username":        u.get("username"),
        "firstName":       u.get("first_name"),
        "balance":         u["stars_balance"],
        "freeSecondsLeft": u["free_seconds_left"],
        "steamUrl":        u.get("steam_trade_url") or "",
        "steam":           steam_out(u),
        "deposits":        u.get("deposits", 0),
    }


def _me(user: dict) -> dict:
    return me_out(dbm.get_me(user["id"], user.get("username"), user.get("first_name"),
                             FREE_CASE_COOLDOWN_H))


# ── Asosiy ma'lumotlar ────────────────────────────────────────────────

@router.post("/bootstrap")
def api_bootstrap(body: Body):
    """WebApp ochilganda bir marta chaqiriladi — hamma kerakli ma'lumot."""
    user = auth(body.initData)
    completed = dbm.get_completed_tasks(user["id"])
    tasks = []
    if CHANNEL_USERNAME:
        tasks.append({"id": "join_channel", "title": "Kanalga obuna bo'ling",
                      "channel": CHANNEL_USERNAME, "reward": TASK_BONUS_STARS,
                      "completed": "join_channel" in completed})
    return {
        "me": _me(user),
        "cases": catalog.public_cases(),
        "skins": [catalog.skin(k) for k in catalog.SKINS],
        "rarities": catalog.RARITIES,
        "packages": [{"id": k, **p} for k, p in catalog.PACKAGES.items()],
        "tasks": tasks,
        "refLink": f"https://t.me/{BOT_USERNAME}?start=ref_{user['id']}" if BOT_USERNAME else "",
        "imgVersion": dbm.image_version(),
        "media": sorted((dbm.image_keys() | media.static_keys()) & media.ALL_KEYS),
        "config": {
            "minBet": MIN_BET, "maxBet": MAX_BET, "maxWin": MAX_WIN,
            "sellRate": SELL_RATE_PERCENT, "minWithdraw": MIN_WITHDRAW_VALUE,
            "withdrawNeedsDeposit": bool(WITHDRAW_NEEDS_DEPOSIT),
            "upgradeRtp": UPGRADE_RTP_PERCENT, "upgradeMaxChance": games.UPGRADE_MAX_CHANCE,
            "contractRtp": CONTRACT_RTP_PERCENT, "contractMin": games.CONTRACT_MIN,
            "contractMax": games.CONTRACT_MAX, "crashRtp": CRASH_RTP_PERCENT,
            "diceRtp": DICE_RTP_PERCENT, "freeCooldownH": FREE_CASE_COOLDOWN_H,
            "refBonus": REFERRAL_BONUS_STARS,
        },
    }


@router.post("/me")
def api_me(body: Body):
    return _me(auth(body.initData))


@router.get("/feed")
def api_feed():
    return {"feed": [{**item_out({**r, "prize_image": ""}), "who": _mask(r["who"]), "source": r["source"]}
                     for r in dbm.get_feed()]}


@router.get("/leaderboard")
def api_leaderboard():
    return {"leaderboard": [{"who": _mask(r["who"]), "total": int(r["total"]), "drops": r["drops"]}
                            for r in dbm.get_leaderboard()]}


def _mask(name) -> str:
    name = str(name or "o'yinchi")
    return name if len(name) <= 3 else name[:3] + "***"


# ── Case'lar ──────────────────────────────────────────────────────────

@router.post("/open-case")
def api_open_case(body: OpenBody):
    user = auth(body.initData)
    case = catalog.CASE_BY_ID.get(body.caseId)
    if not case:
        raise HTTPException(status_code=400, detail="unknown_case")
    dbm.get_or_create_user(user["id"], user.get("username"), user.get("first_name"))
    res = game_call(dbm.open_case, user["id"], case, body.qty, FREE_CASE_COOLDOWN_H, catalog.pick)
    for r in res["results"]:
        r["id"] = r["inventoryId"]
        r["sell"] = max(1, r["value"] * SELL_RATE_PERCENT // 100)
    return res


# ── Inventar ──────────────────────────────────────────────────────────

@router.post("/inventory")
def api_inventory(body: Body):
    user = auth(body.initData)
    return {"items": [item_out(r) for r in dbm.get_inventory(user["id"])]}


@router.post("/sell")
def api_sell(body: ItemsBody):
    user = auth(body.initData)
    if not body.all and not body.ids:
        raise HTTPException(status_code=400, detail="item_not_found")
    return game_call(dbm.sell_items, user["id"], None if body.all else body.ids, SELL_RATE_PERCENT)


@router.post("/withdraw")
async def api_withdraw(body: ItemBody):
    user = auth(body.initData)
    req = await run_in_threadpool(
        game_call, dbm.create_withdraw_request, user["id"], body.inventoryId,
        MIN_WITHDRAW_VALUE, bool(WITHDRAW_NEEDS_DEPOSIT))

    if ADMIN_CHAT_ID:
        uname = ("@" + user["username"]) if user.get("username") else f"id {user['id']}"
        msg = (
            f"📦 <b>Chiqarish so'rovi #{req['id']}</b>\n\n"
            f"👤 {_esc(uname)}\n"
            f"🔫 <b>{_esc(req['prize_name'])}</b> — {req['prize_value']} ⭐\n"
            f"🔗 <code>{_esc(req['steam_trade_url'])}</code>\n\n"
            f"Yubordim: /confirm_{req['id']}\nRad etish: /reject_{req['id']} sabab"
        )
        try:
            await _bot().send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
        except Exception:
            logger.exception("Adminga withdraw xabari yuborilmadi")
    return {"success": True, "requestId": req["id"]}


@router.post("/withdrawals")
def api_withdrawals(body: Body):
    user = auth(body.initData)
    return {"items": dbm.user_withdrawals(user["id"])}


def _valid_trade_url(url: str) -> bool:
    try:
        steam.parse_trade_url(url)
        return True
    except steam.SteamError:
        return False


@router.post("/set-steam")
async def api_set_steam(body: SteamBody):
    """Trade URL ni tekshiradi, Steam profilini topadi va saqlaydi."""
    user = auth(body.initData)
    try:
        clean, partner, _ = steam.parse_trade_url(body.url)
        id64 = steam.to_id64(partner)
        prof = await steam.fetch_profile(id64)
    except steam.SteamError as e:
        raise HTTPException(status_code=400, detail=e.code)
    saved = await run_in_threadpool(
        dbm.set_steam_url, user["id"], clean, id64,
        (prof or {}).get("name"), (prof or {}).get("avatar"))
    return {"success": True, "steam": steam_out(saved), "verified": prof is not None}


def steam_out(u: dict) -> dict | None:
    if not u.get("steam_trade_url"):
        return None
    return {"url": u["steam_trade_url"], "id64": u.get("steam_id64"), "name": u.get("steam_name"),
            "avatar": u.get("steam_avatar"),
            "profile": f"https://steamcommunity.com/profiles/{u['steam_id64']}" if u.get("steam_id64") else None}


# ── O'yinlar ──────────────────────────────────────────────────────────

def _game(fn, *args):
    res = game_call(fn, *args)
    if res.get("item"):
        res["item"]["id"] = res["item"]["inventoryId"]
        res["item"]["sell"] = max(1, res["item"]["value"] * SELL_RATE_PERCENT // 100)
    return res


@router.post("/upgrade")
def api_upgrade(body: UpgradeBody):
    user = auth(body.initData)
    return _game(games.upgrade, user["id"], body.inventoryId, body.targetKey)


@router.post("/contract")
def api_contract(body: ContractBody):
    user = auth(body.initData)
    return _game(games.contract, user["id"], body.ids)


@router.post("/crash")
def api_crash(body: CrashBody):
    user = auth(body.initData)
    return _game(games.crash, user["id"], body.bet, body.target)


@router.post("/dice")
def api_dice(body: DiceBody):
    user = auth(body.initData)
    return _game(games.dice, user["id"], body.bet, body.chance, body.over)


@router.post("/history")
def api_history(body: Body):
    user = auth(body.initData)
    return {"games": dbm.user_games(user["id"])}


# ── Profil ────────────────────────────────────────────────────────────

@router.post("/profile")
def api_profile(body: Body):
    user = auth(body.initData)
    p = dbm.get_profile(user["id"])
    return {
        "casesOpened": p["cases_opened"], "gamesPlayed": p["games_played"],
        "referrals": p["referrals"],
        "best": {"key": p["best_key"] or catalog.key_by_name(p["best_name"]), "name": p["best_name"],
                 "value": p["best_drop"]} if p["best_name"] else None,
    }


@router.post("/tasks/check")
async def api_task_check(body: TaskBody):
    user = auth(body.initData)
    if body.taskId != "join_channel" or not CHANNEL_USERNAME:
        raise HTTPException(status_code=400, detail="unknown_task")
    try:
        member = await _bot().get_chat_member(CHANNEL_USERNAME, user["id"])
    except Exception:
        logger.exception("Obunani tekshirib bo'lmadi (bot kanalda admin bo'lishi kerak)")
        raise HTTPException(status_code=500, detail="check_failed")
    if member.status not in ("member", "administrator", "creator"):
        raise HTTPException(status_code=400, detail="not_member")
    balance = await run_in_threadpool(
        game_call, dbm.complete_task, user["id"], "join_channel", TASK_BONUS_STARS)
    return {"success": True, "reward": TASK_BONUS_STARS, "balance": balance}


@router.post("/create-invoice")
async def api_create_invoice(body: InvoiceBody):
    user = auth(body.initData)
    pkg = catalog.PACKAGES.get(body.package)
    if not pkg:
        raise HTTPException(status_code=400, detail="unknown_package")
    total = pkg["stars"] + pkg["bonus"]
    try:
        link = await _bot().create_invoice_link(
            title=f"{total} Stars balans",
            description=f"Balansingizga {total} Stars qo'shiladi",
            payload=json.dumps({"u": user["id"], "p": body.package}),
            provider_token="",
            currency="XTR",
            prices=[{"label": f"{pkg['stars']} Stars", "amount": pkg["stars"]}],
        )
    except Exception:
        logger.exception("Invoice yaratilmadi")
        raise HTTPException(status_code=500, detail="invoice_failed")
    return {"invoiceLink": link}


def _esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
