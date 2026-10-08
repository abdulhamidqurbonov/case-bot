"""PostgreSQL (Supabase) bilan ishlash.

Qoidalar:
  * Har bir amal bitta tranzaksiyada bajariladi (`with db() as cur:`).
  * Balans, inventar va bepul case faqat ATOMIK so'rovlar bilan o'zgaradi —
    bir vaqtda yuborilgan so'rovlar balansni minusga tushira olmaydi,
    bitta skinni ikki marta sotib/chiqarib bo'lmaydi.
  * Balansning har bir o'zgarishi `balance_log` ga yoziladi (o'yinlar uchun ham shu).
"""
import logging
import math
import threading
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)


class GameError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato (kod frontendga `detail` sifatida boradi)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── Ulanishlar puli ───────────────────────────────────────────────────

_POOL_MAX = 5  # Supabase bepul tarifida ulanishlar cheklangan — ko'p qo'ymang
_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()
# psycopg2 puli to'lganda kutmasdan xato beradi — semafor navbat hosil qiladi
_slots = threading.BoundedSemaphore(_POOL_MAX)
_last_used: dict[int, float] = {}
_IDLE_PING_AFTER_S = 60  # shuncha vaqt ishlatilmagan ulanish avval tekshiriladi


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=_POOL_MAX,
                    dsn=DATABASE_URL,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                    connect_timeout=15,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def _healthy(conn) -> bool:
    if conn.closed:
        return False
    if time.monotonic() - _last_used.get(id(conn), 0) < _IDLE_PING_AFTER_S:
        return True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except psycopg2.Error:
        return False


def _checkout():
    if not _slots.acquire(timeout=30):
        raise psycopg2.OperationalError("Baza band: bo'sh ulanish kutib bo'lmadi")
    try:
        pool = _get_pool()
        for _ in range(3):
            conn = pool.getconn()
            if _healthy(conn):
                return pool, conn
            _last_used.pop(id(conn), None)
            pool.putconn(conn, close=True)
        raise psycopg2.OperationalError("Bazaga ulanib bo'lmadi")
    except BaseException:
        _slots.release()
        raise


@contextmanager
def db():
    """`with db() as cur:` — xato bo'lsa rollback, aks holda commit."""
    pool, conn = _checkout()
    broken = False
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    except BaseException:
        try:
            conn.rollback()
        except psycopg2.Error:
            broken = True
        raise
    finally:
        if broken or conn.closed:
            _last_used.pop(id(conn), None)
            pool.putconn(conn, close=True)
        else:
            _last_used[id(conn)] = time.monotonic()
            pool.putconn(conn)
        _slots.release()


# ── Sxema ─────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id        BIGINT PRIMARY KEY,
    username           TEXT,
    first_name         TEXT,
    stars_balance      INTEGER NOT NULL DEFAULT 0,
    premium_cases      INTEGER NOT NULL DEFAULT 0,
    free_case_used_at  TIMESTAMPTZ,
    steam_trade_url    TEXT,
    referred_by        BIGINT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS case_openings (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT REFERENCES users(telegram_id),
    case_id      TEXT NOT NULL,
    prize_name   TEXT NOT NULL,
    prize_image  TEXT DEFAULT '',
    prize_value  INTEGER NOT NULL,
    prize_rarity TEXT NOT NULL,
    was_free     BOOLEAN DEFAULT FALSE,
    opened_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS inventory (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT REFERENCES users(telegram_id),
    prize_name   TEXT NOT NULL,
    prize_image  TEXT DEFAULT '',
    prize_value  INTEGER NOT NULL,
    prize_rarity TEXT NOT NULL,
    status       TEXT DEFAULT 'active',
    obtained_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS payments (
    id                  BIGSERIAL PRIMARY KEY,
    telegram_id         BIGINT REFERENCES users(telegram_id),
    stars_amount        INTEGER NOT NULL,
    cases_granted       INTEGER DEFAULT 0,
    telegram_charge_id  TEXT UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS withdraw_requests (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id),
    inventory_id    BIGINT REFERENCES inventory(id),
    prize_name      TEXT NOT NULL,
    prize_image     TEXT DEFAULT '',
    steam_trade_url TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    admin_note      TEXT,
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS tasks_completed (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT REFERENCES users(telegram_id),
    task_key     TEXT NOT NULL,
    reward_cases INTEGER DEFAULT 0,
    completed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(telegram_id, task_key)
);
CREATE TABLE IF NOT EXISTS referrals (
    id          BIGSERIAL PRIMARY KEY,
    referrer_id BIGINT REFERENCES users(telegram_id),
    referred_id BIGINT REFERENCES users(telegram_id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS balance_log (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id),
    delta        INTEGER NOT NULL,
    balance      INTEGER NOT NULL,
    reason       TEXT NOT NULL,
    ref          TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS games (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id),
    game         TEXT NOT NULL,
    bet          INTEGER NOT NULL,
    payout       INTEGER NOT NULL,
    win          BOOLEAN NOT NULL,
    details      JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crash_rounds (
    id           BIGSERIAL PRIMARY KEY,
    telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id),
    bet          INTEGER NOT NULL,
    crash        NUMERIC(10,2) NOT NULL,
    auto         NUMERIC(10,2),
    started_at   TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'live',
    cash_mult    NUMERIC(10,2),
    payout       INTEGER NOT NULL DEFAULT 0,
    settled_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS live_rounds (
    id          BIGSERIAL PRIMARY KEY,
    crash       NUMERIC(10,2) NOT NULL,
    takeoff     TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'betting',
    crashed_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS live_bets (
    id           BIGSERIAL PRIMARY KEY,
    round_id     BIGINT NOT NULL REFERENCES live_rounds(id),
    telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id),
    bet          INTEGER NOT NULL,
    auto         NUMERIC(10,2),
    status       TEXT NOT NULL DEFAULT 'active',
    cash_mult    NUMERIC(10,2),
    payout       INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (round_id, telegram_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skin_images (
    key          TEXT PRIMARY KEY,
    data         BYTEA NOT NULL,
    mime         TEXT NOT NULL,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Migratsiyalar (qayta ishga tushirilsa ham xavfsiz)
ALTER TABLE payments  ADD COLUMN IF NOT EXISTS credited_stars INTEGER DEFAULT 0;
ALTER TABLE payments  ADD COLUMN IF NOT EXISTS package TEXT;
ALTER TABLE payments  ALTER COLUMN cases_granted SET DEFAULT 0;
ALTER TABLE payments  ALTER COLUMN cases_granted DROP NOT NULL;
ALTER TABLE tasks_completed ADD COLUMN IF NOT EXISTS reward_stars INTEGER DEFAULT 0;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS reward_given BOOLEAN DEFAULT FALSE;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS skin_key TEXT;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'case';
ALTER TABLE case_openings ADD COLUMN IF NOT EXISTS skin_key TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS steam_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS steam_avatar TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS steam_id64 TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_referrals_referred ON referrals(referred_id);
CREATE INDEX IF NOT EXISTS idx_openings_user   ON case_openings(telegram_id);
CREATE INDEX IF NOT EXISTS idx_inventory_user  ON inventory(telegram_id, status);
CREATE INDEX IF NOT EXISTS idx_inventory_time  ON inventory(obtained_at DESC);
CREATE INDEX IF NOT EXISTS idx_withdraw_status ON withdraw_requests(status);
CREATE INDEX IF NOT EXISTS idx_tasks_user      ON tasks_completed(telegram_id);
CREATE INDEX IF NOT EXISTS idx_referrer        ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_balance_log     ON balance_log(telegram_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_games_user      ON games(telegram_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crash_live      ON crash_rounds(telegram_id) WHERE status = 'live';
CREATE INDEX IF NOT EXISTS idx_live_rounds_st  ON live_rounds(status, id DESC);
CREATE INDEX IF NOT EXISTS idx_live_bets_round ON live_bets(round_id, status);
"""


def init_db() -> None:
    with db() as cur:
        cur.execute(_SCHEMA)
    logger.info("✅ Baza tayyor")


# ── Ichki yordamchilar ────────────────────────────────────────────────

def _ensure_user(cur, telegram_id: int, username=None, first_name=None) -> tuple[dict, bool]:
    cur.execute(
        """
        INSERT INTO users (telegram_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
           SET username   = COALESCE(EXCLUDED.username, users.username),
               first_name = COALESCE(EXCLUDED.first_name, users.first_name)
        RETURNING *, (xmax = 0) AS created
        """,
        (telegram_id, username, first_name),
    )
    row = dict(cur.fetchone())
    created = bool(row.pop("created"))
    return row, created


def _change_balance(cur, telegram_id: int, delta: int, reason: str, ref=None) -> int | None:
    """Balansni atomik o'zgartiradi. Mablag' yetmasa None."""
    cur.execute(
        "UPDATE users SET stars_balance = stars_balance + %s "
        "WHERE telegram_id = %s AND stars_balance + %s >= 0 RETURNING stars_balance",
        (delta, telegram_id, delta),
    )
    row = cur.fetchone()
    if row is None:
        return None
    balance = row["stars_balance"]
    cur.execute(
        "INSERT INTO balance_log (telegram_id, delta, balance, reason, ref) VALUES (%s,%s,%s,%s,%s)",
        (telegram_id, delta, balance, reason, None if ref is None else str(ref)),
    )
    return balance


def _spend(cur, telegram_id: int, amount: int, reason: str, ref=None) -> int:
    balance = _change_balance(cur, telegram_id, -amount, reason, ref)
    if balance is None:
        raise GameError("insufficient_stars")
    return balance


def _add_item(cur, telegram_id: int, sk: dict, source: str) -> dict:
    cur.execute(
        "INSERT INTO inventory (telegram_id, skin_key, prize_name, prize_image, prize_value, prize_rarity, source) "
        "VALUES (%s,%s,%s,'',%s,%s,%s) RETURNING id",
        (telegram_id, sk["key"], sk["name"], sk["value"], sk["rarity"], source),
    )
    return {**sk, "inventoryId": cur.fetchone()["id"]}


def _take_items(cur, telegram_id: int, ids: list[int], new_status: str) -> list[dict]:
    """Foydalanuvchining faol itemlarini atomik oladi. Bittasi ham topilmasa — xato."""
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        raise GameError("item_not_found")
    cur.execute(
        "UPDATE inventory SET status = %s "
        "WHERE telegram_id = %s AND status = 'active' AND id = ANY(%s) "
        "RETURNING id, skin_key, prize_name, prize_value, prize_rarity",
        (new_status, telegram_id, ids),
    )
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) != len(ids):
        raise GameError("item_not_found")  # tranzaksiya bekor bo'ladi
    return rows


def _log_game(cur, telegram_id: int, game: str, bet: int, payout: int, details: dict) -> int:
    cur.execute(
        "INSERT INTO games (telegram_id, game, bet, payout, win, details) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (telegram_id, game, bet, payout, payout > 0, psycopg2.extras.Json(details)),
    )
    return cur.fetchone()["id"]


def change_balance(telegram_id: int, delta: int, reason: str, ref=None) -> int:
    with db() as cur:
        balance = _change_balance(cur, telegram_id, delta, reason, ref)
        if balance is None:
            raise GameError("insufficient_stars")
        return balance


# ── Foydalanuvchi ─────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username=None, first_name=None) -> tuple[dict, bool]:
    with db() as cur:
        return _ensure_user(cur, telegram_id, username, first_name)


def get_me(telegram_id: int, username, first_name, cooldown_h: int) -> dict:
    with db() as cur:
        _ensure_user(cur, telegram_id, username, first_name)
        cur.execute(
            """
            SELECT u.*,
                   GREATEST(0, CEIL(EXTRACT(EPOCH FROM
                       (u.free_case_used_at + make_interval(hours => %s) - NOW()))))::int
                       AS free_seconds_left,
                   (SELECT COUNT(*) FROM payments p WHERE p.telegram_id = u.telegram_id) AS deposits,
                   (SELECT COALESCE(SUM(stars_amount), 0) FROM payments p WHERE p.telegram_id = u.telegram_id)::int AS deposited
              FROM users u WHERE u.telegram_id = %s
            """,
            (cooldown_h, telegram_id),
        )
        row = dict(cur.fetchone())
        row["free_seconds_left"] = row["free_seconds_left"] or 0
        return row


def set_steam_url(telegram_id: int, url: str, id64: str | None = None,
                  name: str | None = None, avatar: str | None = None) -> dict:
    with db() as cur:
        _ensure_user(cur, telegram_id)
        cur.execute(
            "UPDATE users SET steam_trade_url = %s, steam_id64 = %s, steam_name = %s, steam_avatar = %s "
            "WHERE telegram_id = %s RETURNING steam_trade_url, steam_id64, steam_name, steam_avatar",
            (url, id64, name, avatar, telegram_id))
        return dict(cur.fetchone())


# ── Case ochish ───────────────────────────────────────────────────────

def open_case(telegram_id: int, case: dict, qty: int, cooldown_h: int, pick) -> dict:
    is_free = bool(case.get("free"))
    with db() as cur:
        if is_free:
            qty = 1
            cur.execute(
                """
                UPDATE users SET free_case_used_at = NOW()
                 WHERE telegram_id = %s
                   AND (free_case_used_at IS NULL
                        OR free_case_used_at <= NOW() - make_interval(hours => %s))
                RETURNING stars_balance
                """,
                (telegram_id, cooldown_h),
            )
            row = cur.fetchone()
            if row is None:
                raise GameError("free_case_cooldown")
            balance, cost = row["stars_balance"], 0
        else:
            cost = case["price"] * qty
            balance = _spend(cur, telegram_id, cost, "case_open", case["id"])

        results = []
        for _ in range(qty):
            sk = pick(case["id"])
            cur.execute(
                "INSERT INTO case_openings (telegram_id, case_id, skin_key, prize_name, prize_value, "
                "prize_rarity, was_free) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (telegram_id, case["id"], sk["key"], sk["name"], sk["value"], sk["rarity"], is_free),
            )
            results.append(_add_item(cur, telegram_id, sk, "case"))
        return {"results": results, "cost": cost, "balance": balance}


# ── Inventar ──────────────────────────────────────────────────────────

def get_inventory(telegram_id: int) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT id, skin_key, prize_name, prize_image, prize_value, prize_rarity, obtained_at "
            "FROM inventory WHERE telegram_id = %s AND status = 'active' "
            "ORDER BY prize_value DESC, id DESC LIMIT 500",
            (telegram_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_items(telegram_id: int, ids: list[int]) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT id, skin_key, prize_name, prize_value, prize_rarity FROM inventory "
            "WHERE telegram_id = %s AND status = 'active' AND id = ANY(%s)",
            (telegram_id, list(ids)),
        )
        return [dict(r) for r in cur.fetchall()]


def sell_items(telegram_id: int, ids: list[int] | None, rate_percent: int) -> dict:
    """ids=None — barcha faol itemlarni sotadi."""
    with db() as cur:
        if ids is None:
            cur.execute(
                "UPDATE inventory SET status = 'sold' WHERE telegram_id = %s AND status = 'active' "
                "RETURNING id, prize_value",
                (telegram_id,),
            )
            rows = cur.fetchall()
            if not rows:
                raise GameError("item_not_found")
        else:
            rows = _take_items(cur, telegram_id, ids, "sold")
        reward = sum(max(1, r["prize_value"] * rate_percent // 100) for r in rows)
        balance = _change_balance(cur, telegram_id, reward, "sell", ",".join(str(r["id"]) for r in rows)[:200])
        return {"reward": reward, "count": len(rows), "balance": balance}


# ── Steam'ga chiqarish ────────────────────────────────────────────────

def create_withdraw_request(telegram_id: int, inventory_id: int, min_value: int, min_deposit: int,
                            enabled: bool) -> dict:
    if not enabled:
        raise GameError("withdraw_disabled")
    with db() as cur:
        cur.execute(
            "SELECT steam_trade_url, (SELECT COALESCE(SUM(stars_amount), 0) FROM payments p "
            "WHERE p.telegram_id = u.telegram_id) AS deposited FROM users u WHERE telegram_id = %s",
            (telegram_id,),
        )
        user = cur.fetchone()
        if not user or not user["steam_trade_url"]:
            raise GameError("no_steam_url")
        if user["deposited"] < min_deposit:
            raise GameError("deposit_required")
        item = _take_items(cur, telegram_id, [inventory_id], "withdraw_pending")[0]
        if item["prize_value"] < min_value:
            raise GameError("value_too_low")
        cur.execute(
            "INSERT INTO withdraw_requests (telegram_id, inventory_id, prize_name, steam_trade_url) "
            "VALUES (%s,%s,%s,%s) RETURNING *",
            (telegram_id, inventory_id, item["prize_name"], user["steam_trade_url"]),
        )
        return {**dict(cur.fetchone()), "prize_value": item["prize_value"]}


def confirm_withdraw(req_id: int) -> dict | None:
    with db() as cur:
        cur.execute(
            "UPDATE withdraw_requests SET status = 'sent', processed_at = NOW() "
            "WHERE id = %s AND status = 'pending' RETURNING *",
            (req_id,),
        )
        req = cur.fetchone()
        if req is None:
            return None
        cur.execute("UPDATE inventory SET status = 'withdrawn' WHERE id = %s", (req["inventory_id"],))
        return dict(req)


def reject_withdraw(req_id: int, note: str = "") -> dict | None:
    with db() as cur:
        cur.execute(
            "UPDATE withdraw_requests SET status = 'rejected', processed_at = NOW(), admin_note = %s "
            "WHERE id = %s AND status = 'pending' RETURNING *",
            (note or None, req_id),
        )
        req = cur.fetchone()
        if req is None:
            return None
        cur.execute("UPDATE inventory SET status = 'active' WHERE id = %s", (req["inventory_id"],))
        return dict(req)


def list_pending_withdrawals(limit: int = 20) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT w.id, w.prize_name, w.steam_trade_url, w.requested_at, u.username, w.telegram_id "
            "FROM withdraw_requests w LEFT JOIN users u ON u.telegram_id = w.telegram_id "
            "WHERE w.status = 'pending' ORDER BY w.requested_at LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def user_withdrawals(telegram_id: int, limit: int = 20) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT id, prize_name, status, requested_at FROM withdraw_requests "
            "WHERE telegram_id = %s ORDER BY id DESC LIMIT %s",
            (telegram_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


# ── O'yinlar ──────────────────────────────────────────────────────────

def play_stars_game(telegram_id: int, game: str, bet: int, resolve) -> dict:
    """Stars bilan o'ynaladigan o'yin (Crash, Dice).
    resolve() -> (payout, details). Hammasi bitta tranzaksiyada."""
    with db() as cur:
        _spend(cur, telegram_id, bet, game + "_bet")
        payout, details = resolve()
        balance = None
        if payout > 0:
            balance = _change_balance(cur, telegram_id, payout, game + "_win")
        game_id = _log_game(cur, telegram_id, game, bet, payout, details)
        if balance is None:
            cur.execute("SELECT stars_balance FROM users WHERE telegram_id = %s", (telegram_id,))
            balance = cur.fetchone()["stars_balance"]
        return {"gameId": game_id, "bet": bet, "payout": payout, "win": payout > 0,
                "balance": balance, **details}


def play_item_game(telegram_id: int, game: str, ids: list[int], resolve) -> dict:
    """Skin bilan o'ynaladigan o'yin (Upgrade, Contract).
    resolve(items) -> (yutgan skin yoki None, details)."""
    with db() as cur:
        items = _take_items(cur, telegram_id, ids, game)
        stake = sum(i["prize_value"] for i in items)
        won, details = resolve(items)
        new_item = _add_item(cur, telegram_id, won, game) if won else None
        game_id = _log_game(cur, telegram_id, game, stake, won["value"] if won else 0,
                            {**details, "items": [i["id"] for i in items]})
        return {"gameId": game_id, "stake": stake, "win": bool(won), "item": new_item, **details}


def user_games(telegram_id: int, limit: int = 30) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT id, game, bet, payout, win, details, created_at FROM games "
            "WHERE telegram_id = %s ORDER BY id DESC LIMIT %s",
            (telegram_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


# ── To'lovlar ─────────────────────────────────────────────────────────

def save_payment(telegram_id: int, paid_stars: int, credit_stars: int,
                 charge_id: str, package: str, username=None, first_name=None) -> int | None:
    """Takroriy charge_id bo'lsa — None."""
    with db() as cur:
        _ensure_user(cur, telegram_id, username, first_name)
        cur.execute(
            "INSERT INTO payments (telegram_id, stars_amount, credited_stars, telegram_charge_id, package) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (telegram_charge_id) DO NOTHING RETURNING id",
            (telegram_id, paid_stars, credit_stars, charge_id, package),
        )
        if cur.fetchone() is None:
            return None
        return _change_balance(cur, telegram_id, credit_stars, "payment", charge_id)


# ── Vazifalar ─────────────────────────────────────────────────────────

def get_completed_tasks(telegram_id: int) -> set[str]:
    with db() as cur:
        cur.execute("SELECT task_key FROM tasks_completed WHERE telegram_id = %s", (telegram_id,))
        return {r["task_key"] for r in cur.fetchall()}


def complete_task(telegram_id: int, task_key: str, reward_stars: int) -> int:
    with db() as cur:
        _ensure_user(cur, telegram_id)
        cur.execute(
            "INSERT INTO tasks_completed (telegram_id, task_key, reward_stars) VALUES (%s,%s,%s) "
            "ON CONFLICT (telegram_id, task_key) DO NOTHING RETURNING id",
            (telegram_id, task_key, reward_stars),
        )
        if cur.fetchone() is None:
            raise GameError("already_completed")
        return _change_balance(cur, telegram_id, reward_stars, "task", task_key)


# ── Referallar ────────────────────────────────────────────────────────

def register_referral(referrer_id: int, referred_id: int, bonus_stars: int) -> bool:
    if referrer_id == referred_id:
        return False
    with db() as cur:
        cur.execute(
            "INSERT INTO referrals (referrer_id, referred_id, reward_given) "
            "SELECT %s, %s, TRUE "
            "WHERE EXISTS (SELECT 1 FROM users WHERE telegram_id = %s) "
            "  AND EXISTS (SELECT 1 FROM users WHERE telegram_id = %s) "
            "ON CONFLICT (referred_id) DO NOTHING RETURNING id",
            (referrer_id, referred_id, referrer_id, referred_id),
        )
        if cur.fetchone() is None:
            return False
        cur.execute("UPDATE users SET referred_by = %s WHERE telegram_id = %s", (referrer_id, referred_id))
        if bonus_stars > 0:
            _change_balance(cur, referrer_id, bonus_stars, "referral", referred_id)
        return True


# ── Profil, lenta, reyting ────────────────────────────────────────────

def get_profile(telegram_id: int) -> dict:
    with db() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM case_openings WHERE telegram_id = %(u)s) AS cases_opened,
              (SELECT COUNT(*) FROM games WHERE telegram_id = %(u)s)         AS games_played,
              (SELECT COUNT(*) FROM referrals WHERE referrer_id = %(u)s)     AS referrals,
              (SELECT MAX(prize_value) FROM inventory WHERE telegram_id = %(u)s) AS best_drop,
              (SELECT prize_name FROM inventory WHERE telegram_id = %(u)s
                 ORDER BY prize_value DESC, id LIMIT 1)                     AS best_name,
              (SELECT skin_key FROM inventory WHERE telegram_id = %(u)s
                 ORDER BY prize_value DESC, id LIMIT 1)                     AS best_key
            """,
            {"u": telegram_id},
        )
        return dict(cur.fetchone())


def get_feed(limit: int = 20) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT i.id, i.skin_key, i.prize_name, i.prize_value, i.prize_rarity, i.source, "
            "       COALESCE(u.username, u.first_name) AS who "
            "FROM inventory i JOIN users u ON u.telegram_id = i.telegram_id "
            "ORDER BY i.id DESC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_leaderboard(limit: int = 10) -> list[dict]:
    with db() as cur:
        cur.execute(
            """
            SELECT COALESCE(u.username, u.first_name) AS who,
                   SUM(i.prize_value)::bigint AS total, COUNT(*) AS drops
              FROM inventory i JOIN users u ON u.telegram_id = i.telegram_id
             WHERE i.obtained_at > NOW() - INTERVAL '7 days'
             GROUP BY u.telegram_id, who
             ORDER BY total DESC
             LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


# ── Skin rasmlari ─────────────────────────────────────────────────────

def save_skin_image(key: str, data: bytes, mime: str) -> None:
    with db() as cur:
        cur.execute(
            "INSERT INTO skin_images (key, data, mime) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, mime = EXCLUDED.mime, updated_at = NOW()",
            (key, psycopg2.Binary(data), mime),
        )


def delete_skin_image(key: str) -> bool:
    with db() as cur:
        cur.execute("DELETE FROM skin_images WHERE key = %s RETURNING key", (key,))
        return cur.fetchone() is not None


def get_skin_image(key: str) -> tuple[bytes, str] | None:
    with db() as cur:
        cur.execute("SELECT data, mime FROM skin_images WHERE key = %s", (key,))
        row = cur.fetchone()
        return (bytes(row["data"]), row["mime"]) if row else None


def image_keys() -> set[str]:
    with db() as cur:
        cur.execute("SELECT key FROM skin_images")
        return {r["key"] for r in cur.fetchall()}


def image_version() -> int:
    with db() as cur:
        cur.execute("SELECT COALESCE(EXTRACT(EPOCH FROM MAX(updated_at)), 0)::bigint AS v FROM skin_images")
        return cur.fetchone()["v"]


# ── Sozlamalar (bot orqali o'zgaradi, deploy kerak emas) ───────────────

def get_setting(key: str, default: str | None = None) -> str | None:
    with db() as cur:
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as cur:
        cur.execute("INSERT INTO settings (key, value) VALUES (%s,%s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))


def admin_stats() -> dict:
    with db() as cur:
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM users)                                              AS users,
              (SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '1 day')  AS users_day,
              (SELECT COUNT(*) FROM payments)                                           AS pay_count,
              (SELECT COALESCE(SUM(stars_amount), 0) FROM payments)::bigint             AS pay_stars,
              (SELECT COALESCE(SUM(stars_amount), 0) FROM payments
                WHERE created_at > NOW() - INTERVAL '1 day')::bigint                    AS pay_stars_day,
              (SELECT COUNT(DISTINCT telegram_id) FROM payments)                        AS payers,
              (SELECT COALESCE(SUM(stars_balance), 0) FROM users)::bigint               AS balances,
              (SELECT COALESCE(SUM(prize_value), 0) FROM inventory WHERE status = 'active')::bigint AS inv_value,
              (SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending')         AS wd_pending,
              (SELECT COALESCE(SUM(i.prize_value), 0) FROM withdraw_requests w
                 JOIN inventory i ON i.id = w.inventory_id WHERE w.status = 'pending')::bigint AS wd_pending_value,
              (SELECT COUNT(*) FROM withdraw_requests WHERE status = 'sent')            AS wd_sent,
              (SELECT COALESCE(SUM(bet), 0) - COALESCE(SUM(payout), 0) FROM games)::bigint AS games_profit,
              (SELECT COALESCE(SUM(bet), 0) - COALESCE(SUM(payout), 0) FROM live_bets
                WHERE status IN ('cashed', 'lost'))::bigint                             AS crash_profit
        """)
        return dict(cur.fetchone())


# ── Crash (samolyot) ──────────────────────────────────────────────────
# Koeffitsiyent vaqtga bog'liq: m(t) = e^(k·t). Hammasi server soati bo'yicha hisoblanadi.

_CRASH_SETTLE_SQL = """
    UPDATE crash_rounds r SET
        status = CASE WHEN r.auto IS NOT NULL AND r.crash >= r.auto THEN 'auto' ELSE 'lost' END,
        cash_mult = CASE WHEN r.auto IS NOT NULL AND r.crash >= r.auto THEN r.auto END,
        payout = CASE WHEN r.auto IS NOT NULL AND r.crash >= r.auto THEN FLOOR(r.bet * r.auto)::int ELSE 0 END,
        settled_at = clock_timestamp()
    WHERE r.telegram_id = %(u)s AND r.status = 'live'
      AND clock_timestamp() >= r.started_at + make_interval(secs => LN(r.crash) / %(k)s)
    RETURNING r.*
"""


def _crash_finish(cur, rows) -> None:
    for r in rows:
        if r["payout"] > 0:
            _change_balance(cur, r["telegram_id"], r["payout"], "crash_win", r["id"])
        _log_game(cur, r["telegram_id"], "crash", r["bet"], r["payout"],
                  {"crash": float(r["crash"]), "cashout": float(r["cash_mult"]) if r["cash_mult"] else None,
                   "round": r["id"]})


def crash_settle(telegram_id: int, k: float) -> None:
    with db() as cur:
        cur.execute(_CRASH_SETTLE_SQL, {"u": telegram_id, "k": k})
        _crash_finish(cur, cur.fetchall())


def crash_start(telegram_id: int, bet: int, auto: float | None, crash: float, k: float, delay: float) -> dict:
    with db() as cur:
        # Oldingi (tugagan) raundlarni hisob-kitob qilamiz
        cur.execute(_CRASH_SETTLE_SQL, {"u": telegram_id, "k": k})
        _crash_finish(cur, cur.fetchall())
        cur.execute("SELECT id FROM crash_rounds WHERE telegram_id = %s AND status = 'live' FOR UPDATE",
                    (telegram_id,))
        if cur.fetchone():
            raise GameError("round_active")
        balance = _spend(cur, telegram_id, bet, "crash_bet")
        cur.execute(
            "INSERT INTO crash_rounds (telegram_id, bet, crash, auto, started_at) "
            "VALUES (%s,%s,%s,%s, clock_timestamp() + make_interval(secs => %s)) RETURNING id",
            (telegram_id, bet, crash, auto, delay),
        )
        return {"roundId": cur.fetchone()["id"], "startsIn": delay, "balance": balance}


def crash_cashout(telegram_id: int, round_id: int, k: float, latency: float) -> dict:
    """Qo'lda yechib olish. Samolyot hali uchayotgan bo'lsa — yutuq, aks holda raund yakunlanadi."""
    with db() as cur:
        cur.execute(
            "SELECT *, EXTRACT(EPOCH FROM clock_timestamp() - started_at)::float AS elapsed "
            "FROM crash_rounds WHERE id = %s AND telegram_id = %s FOR UPDATE",
            (round_id, telegram_id),
        )
        r = cur.fetchone()
        if not r:
            raise GameError("round_not_found")
        if r["status"] != "live":
            return _crash_out(cur, r)
        elapsed = r["elapsed"]
        if elapsed < 0:
            raise GameError("not_started")
        crash = float(r["crash"])
        mult = math.floor(100 * math.exp(k * max(0.0, elapsed - latency))) / 100
        auto = float(r["auto"]) if r["auto"] is not None else None
        if auto is not None and auto <= mult and crash >= auto:
            mult = auto                       # avto-yechish oldinroq ishlagan bo'lardi
        if mult < crash or (auto is not None and mult == auto and crash >= auto):
            payout = int(r["bet"] * mult)
            cur.execute(
                "UPDATE crash_rounds SET status = 'cashed', cash_mult = %s, payout = %s, settled_at = clock_timestamp() "
                "WHERE id = %s RETURNING *", (mult, payout, round_id))
            row = cur.fetchone()
            _crash_finish(cur, [row])
            return _crash_out(cur, row, reveal=False)
        # Kech qoldi — samolyot uchib ketgan
        cur.execute(_CRASH_SETTLE_SQL, {"u": telegram_id, "k": k})
        _crash_finish(cur, cur.fetchall())
        cur.execute("SELECT * FROM crash_rounds WHERE id = %s", (round_id,))
        row = cur.fetchone()
        if row["status"] == "live":           # soat farqi: crash vaqtiga millisekundlar qolgan
            cur.execute("UPDATE crash_rounds SET status = 'lost', settled_at = clock_timestamp() "
                        "WHERE id = %s RETURNING *", (round_id,))
            row = cur.fetchone()
            _crash_finish(cur, [row])
        return _crash_out(cur, row)


def crash_round(telegram_id: int, round_id: int) -> dict | None:
    with db() as cur:
        cur.execute(
            "SELECT *, EXTRACT(EPOCH FROM clock_timestamp() - started_at)::float AS elapsed "
            "FROM crash_rounds WHERE id = %s AND telegram_id = %s", (round_id, telegram_id))
        r = cur.fetchone()
        return dict(r) if r else None


def crash_result(telegram_id: int, round_id: int, k: float) -> dict:
    with db() as cur:
        cur.execute(_CRASH_SETTLE_SQL, {"u": telegram_id, "k": k})
        _crash_finish(cur, cur.fetchall())
        cur.execute("SELECT * FROM crash_rounds WHERE id = %s AND telegram_id = %s", (round_id, telegram_id))
        r = cur.fetchone()
        if not r:
            raise GameError("round_not_found")
        return _crash_out(cur, r)


def _crash_out(cur, r, reveal: bool = True) -> dict:
    cur.execute("SELECT stars_balance FROM users WHERE telegram_id = %s", (r["telegram_id"],))
    out = {"roundId": r["id"], "status": r["status"], "payout": r["payout"],
           "cashout": float(r["cash_mult"]) if r["cash_mult"] is not None else None,
           "balance": cur.fetchone()["stars_balance"]}
    if reveal and r["status"] != "live":
        out["crash"] = float(r["crash"])
    return out


def crash_history(limit: int = 20) -> list[float]:
    with db() as cur:
        cur.execute("SELECT crash FROM crash_rounds WHERE status <> 'live' ORDER BY id DESC LIMIT %s", (limit,))
        return [float(r["crash"]) for r in cur.fetchall()]


# ── Jonli Crash (hamma uchun umumiy raund) ────────────────────────────

def _epoch(cur) -> float:
    cur.execute("SELECT EXTRACT(EPOCH FROM clock_timestamp())::float AS t")
    return cur.fetchone()["t"]


def live_recover() -> int:
    """Server qayta ishga tushganda tugallanmagan raundlarni bekor qilib, stavkalarni qaytaradi."""
    n = 0
    with db() as cur:
        cur.execute("UPDATE live_rounds SET status = 'void', crashed_at = clock_timestamp() "
                    "WHERE status IN ('betting', 'flying') RETURNING id")
        ids = [r["id"] for r in cur.fetchall()]
        if ids:
            cur.execute("UPDATE live_bets SET status = 'refunded' WHERE round_id = ANY(%s) AND status = 'active' "
                        "RETURNING telegram_id, bet, round_id", (ids,))
            for b in cur.fetchall():
                _change_balance(cur, b["telegram_id"], b["bet"], "crash_refund", b["round_id"])
                n += 1
    return n


def live_new_round(crash: float, bet_secs: float) -> dict:
    with db() as cur:
        cur.execute(
            "INSERT INTO live_rounds (crash, takeoff) VALUES (%s, clock_timestamp() + make_interval(secs => %s)) "
            "RETURNING id, EXTRACT(EPOCH FROM takeoff)::float AS takeoff", (crash, bet_secs))
        r = dict(cur.fetchone())
        r["now"] = _epoch(cur)
        return r


def live_takeoff(round_id: int) -> list[float]:
    """Raundni «uchish» holatiga o'tkazadi. Avto-yechish qiymatlarini qaytaradi."""
    with db() as cur:
        cur.execute("UPDATE live_rounds SET status = 'flying' WHERE id = %s AND status = 'betting'", (round_id,))
        cur.execute("SELECT DISTINCT auto FROM live_bets WHERE round_id = %s AND status = 'active' AND auto IS NOT NULL "
                    "ORDER BY auto", (round_id,))
        return [float(r["auto"]) for r in cur.fetchall()]


def _settle_bets(cur, rows, crash: float) -> None:
    for b in rows:
        if b["payout"] > 0:
            _change_balance(cur, b["telegram_id"], b["payout"], "crash_win", b["round_id"])
        _log_game(cur, b["telegram_id"], "crash", b["bet"], b["payout"],
                  {"crash": crash, "cashout": float(b["cash_mult"]) if b["cash_mult"] is not None else None,
                   "round": b["round_id"], "live": True})


def live_settle_auto(round_id: int, upto: float, crash: float) -> int:
    """auto <= upto bo'lgan faol stavkalarni avto-koeffitsiyentda yechib oladi."""
    with db() as cur:
        cur.execute(
            "UPDATE live_bets SET status = 'cashed', cash_mult = auto, payout = FLOOR(bet * auto)::int "
            "WHERE round_id = %s AND status = 'active' AND auto IS NOT NULL AND auto <= %s AND auto <= %s RETURNING *",
            (round_id, upto, crash))
        rows = cur.fetchall()
        _settle_bets(cur, rows, crash)
        return len(rows)


def live_crash(round_id: int, crash: float) -> None:
    with db() as cur:
        cur.execute("UPDATE live_rounds SET status = 'crashed', crashed_at = clock_timestamp() WHERE id = %s", (round_id,))
        # o'tkazib yuborilgan avto-yechishlar (ehtiyot uchun) — keyin qolganlari yutqazdi
        cur.execute(
            "UPDATE live_bets SET status = 'cashed', cash_mult = auto, payout = FLOOR(bet * auto)::int "
            "WHERE round_id = %s AND status = 'active' AND auto IS NOT NULL AND auto <= %s RETURNING *",
            (round_id, crash))
        _settle_bets(cur, cur.fetchall(), crash)
        cur.execute("UPDATE live_bets SET status = 'lost' WHERE round_id = %s AND status = 'active' RETURNING *",
                    (round_id,))
        _settle_bets(cur, cur.fetchall(), crash)


def live_bet(telegram_id: int, round_id: int, bet: int, auto: float | None) -> dict:
    with db() as cur:
        cur.execute("SELECT status, EXTRACT(EPOCH FROM takeoff - clock_timestamp())::float AS left_s "
                    "FROM live_rounds WHERE id = %s FOR SHARE", (round_id,))
        r = cur.fetchone()
        if not r or r["status"] != "betting" or r["left_s"] < 0.25:
            raise GameError("betting_closed")
        cur.execute("INSERT INTO live_bets (round_id, telegram_id, bet, auto) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (round_id, telegram_id) DO NOTHING RETURNING id", (round_id, telegram_id, bet, auto))
        if cur.fetchone() is None:
            raise GameError("already_bet")
        balance = _spend(cur, telegram_id, bet, "crash_bet", round_id)
        return {"roundId": round_id, "balance": balance}


def live_cancel(telegram_id: int, round_id: int) -> dict:
    with db() as cur:
        cur.execute("SELECT status, EXTRACT(EPOCH FROM takeoff - clock_timestamp())::float AS left_s "
                    "FROM live_rounds WHERE id = %s FOR SHARE", (round_id,))
        r = cur.fetchone()
        if not r or r["status"] != "betting" or r["left_s"] < 0.25:
            raise GameError("betting_closed")
        cur.execute("DELETE FROM live_bets WHERE round_id = %s AND telegram_id = %s AND status = 'active' RETURNING bet",
                    (round_id, telegram_id))
        b = cur.fetchone()
        if not b:
            raise GameError("round_not_found")
        balance = _change_balance(cur, telegram_id, b["bet"], "crash_cancel", round_id)
        return {"roundId": round_id, "balance": balance}


def live_cashout(telegram_id: int, round_id: int, k: float, latency: float) -> dict:
    with db() as cur:
        cur.execute(
            "SELECT b.*, r.crash, r.status AS rstatus, "
            "EXTRACT(EPOCH FROM clock_timestamp() - r.takeoff)::float AS elapsed "
            "FROM live_bets b JOIN live_rounds r ON r.id = b.round_id "
            "WHERE b.round_id = %s AND b.telegram_id = %s FOR UPDATE OF b", (round_id, telegram_id))
        b = cur.fetchone()
        if not b:
            raise GameError("round_not_found")
        if b["status"] == "active" and b["rstatus"] == "flying":
            if b["elapsed"] < 0:
                raise GameError("not_started")
            crash = float(b["crash"])
            mult = math.floor(100 * math.exp(k * max(0.0, b["elapsed"] - latency))) / 100
            auto = float(b["auto"]) if b["auto"] is not None else None
            if auto is not None and auto <= mult and auto <= crash:
                mult = auto
            if mult < crash or (auto is not None and mult == auto):
                cur.execute("UPDATE live_bets SET status = 'cashed', cash_mult = %s, payout = %s WHERE id = %s RETURNING *",
                            (mult, int(b["bet"] * mult), b["id"]))
                row = cur.fetchone()
                _settle_bets(cur, [row], crash)
                b = {**b, **row}
        cur.execute("SELECT stars_balance FROM users WHERE telegram_id = %s", (telegram_id,))
        return {"roundId": round_id, "status": b["status"], "payout": b["payout"],
                "cashout": float(b["cash_mult"]) if b["cash_mult"] is not None else None,
                "balance": cur.fetchone()["stars_balance"]}


def live_snapshot(limit_bets: int = 60) -> dict:
    """Hamma uchun bir xil holat: joriy raund, stavkalar, tarix."""
    with db() as cur:
        now = _epoch(cur)
        cur.execute("SELECT id, crash, status, EXTRACT(EPOCH FROM takeoff)::float AS takeoff, "
                    "EXTRACT(EPOCH FROM crashed_at)::float AS crashed_at FROM live_rounds ORDER BY id DESC LIMIT 1")
        r = cur.fetchone()
        rnd, bets, total = None, [], 0
        if r:
            rnd = {"id": r["id"], "status": r["status"], "takeoff": r["takeoff"], "crashedAt": r["crashed_at"]}
            if r["status"] in ("crashed", "void"):
                rnd["crash"] = float(r["crash"])
            cur.execute(
                "SELECT b.telegram_id, b.bet, b.status, b.cash_mult, b.payout, COALESCE(u.username, u.first_name) AS who "
                "FROM live_bets b JOIN users u ON u.telegram_id = b.telegram_id "
                "WHERE b.round_id = %s ORDER BY b.bet DESC, b.id LIMIT %s", (r["id"], limit_bets))
            bets = [dict(x) for x in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS n FROM live_bets WHERE round_id = %s", (r["id"],))
            total = cur.fetchone()["n"]
        cur.execute("SELECT crash FROM live_rounds WHERE status = 'crashed' ORDER BY id DESC LIMIT 20")
        hist = [float(x["crash"]) for x in cur.fetchall()]
        return {"now": now, "round": rnd, "bets": bets, "players": total, "hist": hist}
