"""O'yin mantiqi. Natija FAQAT serverda hisoblanadi — frontend faqat animatsiya ko'rsatadi."""
import math

from app import catalog
from app import database as dbm
from app.config import (
    CONTRACT_RTP_PERCENT, CRASH_RTP_PERCENT, DICE_RTP_PERCENT,
    MAX_BET, MAX_WIN, MIN_BET, UPGRADE_RTP_PERCENT,
)

rng = catalog.rng
GameError = dbm.GameError

UPGRADE_MAX_CHANCE = 0.75      # eng yuqori imkoniyat
CONTRACT_MIN, CONTRACT_MAX = 3, 10
CRASH_MAX = 1000.0


def _check_bet(bet: int) -> None:
    if bet < MIN_BET:
        raise GameError("bet_too_low")
    if bet > MAX_BET:
        raise GameError("bet_too_high")


# ── Upgrade ───────────────────────────────────────────────────────────

def upgrade_chance(stake: int, target_value: int) -> float:
    return min(UPGRADE_MAX_CHANCE, stake / target_value * UPGRADE_RTP_PERCENT / 100)


def upgrade(telegram_id: int, inventory_id: int, target_key: str) -> dict:
    target = catalog.skin(target_key)
    if not target:
        raise GameError("unknown_skin")

    def resolve(items):
        stake = sum(i["prize_value"] for i in items)
        if target["value"] <= stake:
            raise GameError("target_too_cheap")
        chance = upgrade_chance(stake, target["value"])
        roll = rng.random()
        win = roll < chance
        return (target if win else None), {"chance": round(chance, 4), "roll": round(roll, 4),
                                           "target": target}

    return dbm.play_item_game(telegram_id, "upgrade", [inventory_id], resolve)


# ── Shartnoma (Contract) ──────────────────────────────────────────────

def _contract_weights(cands: list[dict], target_ev: float) -> list[float]:
    """w = 1/value^a; a ni shunday tanlaymizki o'rtacha qiymat = target_ev."""
    def ev(a):
        ws = [1 / c["value"] ** a for c in cands]
        return sum(w * c["value"] for w, c in zip(ws, cands)) / sum(ws)
    lo, hi = -12.0, 12.0          # manfiy a — qimmatlarga ko'proq og'irlik
    if ev(lo) <= target_ev:
        a = lo
    elif ev(hi) >= target_ev:
        a = hi
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            if ev(mid) > target_ev:
                lo = mid
            else:
                hi = mid
        a = (lo + hi) / 2
    return [1 / c["value"] ** a for c in cands]


def contract_candidates(total: int) -> list[dict]:
    lo, hi = total * 0.1, total * 5
    return [catalog.skin(k) for k, v in catalog.SKINS.items() if lo <= v[2] <= hi]


def contract_pool(total: int, rtp_percent: float) -> tuple[list[dict], list[float]]:
    """Natija variantlari va og'irliklari. O'rtacha qiymat har doim ≈ total × RTP."""
    target = total * rtp_percent / 100
    cands = contract_candidates(total)
    if len(cands) < 2 or min(c["value"] for c in cands) > target:
        # Oraliqda yetarli skin yo'q — arzonroqlarini ham qo'shamiz (uy zarar ko'rmasligi uchun)
        cands = [catalog.skin(k) for k, v in catalog.SKINS.items() if v[2] <= total * 5]
    if len(cands) < 2:
        raise GameError("contract_no_targets")
    return cands, _contract_weights(cands, target)


def contract(telegram_id: int, ids: list[int]) -> dict:
    ids = list(dict.fromkeys(ids))
    if not CONTRACT_MIN <= len(ids) <= CONTRACT_MAX:
        raise GameError("contract_count")

    def resolve(items):
        total = sum(i["prize_value"] for i in items)
        cands, weights = contract_pool(total, CONTRACT_RTP_PERCENT)
        won = rng.choices(cands, weights=weights, k=1)[0]
        return won, {"total": total}

    return dbm.play_item_game(telegram_id, "contract", ids, resolve)


# ── Crash ─────────────────────────────────────────────────────────────

def crash_point() -> float:
    u = rng.random()
    x = math.floor(100 * (CRASH_RTP_PERCENT / 100) / (1 - u)) / 100
    return max(1.0, min(CRASH_MAX, x))


def crash(telegram_id: int, bet: int, target: float) -> dict:
    _check_bet(bet)
    target = round(float(target), 2)
    if not 1.01 <= target <= CRASH_MAX:
        raise GameError("bad_target")
    if bet * target > MAX_WIN:
        raise GameError("win_too_high")

    def resolve():
        point = crash_point()
        payout = int(bet * target) if point >= target else 0
        return payout, {"crash": point, "target": target}

    return dbm.play_stars_game(telegram_id, "crash", bet, resolve)


# ── Dice ──────────────────────────────────────────────────────────────

def dice_multiplier(chance: float) -> float:
    return math.floor(DICE_RTP_PERCENT / chance * 100) / 100


def dice(telegram_id: int, bet: int, chance: float, over: bool) -> dict:
    _check_bet(bet)
    chance = round(float(chance), 2)
    if not 1 <= chance <= 95:
        raise GameError("bad_chance")
    mult = dice_multiplier(chance)
    if bet * mult > MAX_WIN:
        raise GameError("win_too_high")

    def resolve():
        roll = rng.randrange(10000) / 100           # 0.00 … 99.99
        win = roll >= 100 - chance if over else roll < chance
        payout = int(bet * mult) if win else 0
        return payout, {"roll": roll, "chance": chance, "over": over, "multiplier": mult}

    return dbm.play_stars_game(telegram_id, "dice", bet, resolve)
