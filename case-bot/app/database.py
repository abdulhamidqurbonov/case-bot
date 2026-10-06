"""PostgreSQL (Supabase) bilan ishlash.

Qoidalar:
  * Har bir amal bitta tranzaksiyada bajariladi (`with db() as cur:`).
  * Balans, inventar va bepul case faqat ATOMIK so'rovlar bilan o'zgaradi —
    bir vaqtda yuborilgan so'rovlar balansni minusga tushira olmaydi,
    bitta skinni ikki marta sotib/chiqarib bo'lmaydi.
  * Balansning har bir o'zgarishi `balance_log` ga yoziladi (o'yinlar uchun ham shu).
"""
import logging
import threading
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from app.config import DATABASE_URL, SELL_RATE_PERCENT

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

-- Eski bazalar uchun migratsiyalar (qayta ishga tushirilsa ham xavfsiz)
ALTER TABLE payments  ADD COLUMN IF NOT EXISTS credited_stars INTEGER DEFAULT 0;
ALTER TABLE payments  ADD COLUMN IF NOT EXISTS package TEXT;
ALTER TABLE payments  ALTER COLUMN cases_granted SET DEFAULT 0;
ALTER TABLE payments  ALTER COLUMN cases_granted DROP NOT NULL;
ALTER TABLE tasks_completed ADD COLUMN IF NOT EXISTS reward_stars INTEGER DEFAULT 0;
ALTER TABLE referrals ADD COLUMN IF NOT EXISTS reward_given BOOLEAN DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_referrals_referred ON referrals(referred_id);
CREATE INDEX IF NOT EXISTS idx_openings_user   ON case_openings(telegram_id);
CREATE INDEX IF NOT EXISTS idx_inventory_user  ON inventory(telegram_id, status);
CREATE INDEX IF NOT EXISTS idx_withdraw_status ON withdraw_requests(status);
CREATE INDEX IF NOT EXISTS idx_tasks_user      ON tasks_completed(telegram_id);
CREATE INDEX IF NOT EXISTS idx_referrer        ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_balance_log     ON balance_log(telegram_id, created_at DESC);
"""


def init_db() -> None:
    with db() as cur:
        cur.execute(_SCHEMA)
    logger.info("✅ Baza tayyor")


# ── Ichki yordamchilar ────────────────────────────────────────────────

def _ensure_user(cur, telegram_id: int, username=None, first_name=None) -> tuple[dict, bool]:
    """Foydalanuvchini yaratadi yoki yangilaydi. (user, yangi_yaratildimi) qaytaradi."""
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
    """Balansni atomik o'zgartiradi. Mablag' yetmasa None qaytaradi."""
    cur.execute(
        "UPDATE users SET stars_balance = stars_balance + %s "
        "WHERE telegram_id = %s AND stars_balance + %s >= 0 "
        "RETURNING stars_balance",
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


def change_balance(telegram_id: int, delta: int, reason: str, ref=None) -> int:
    """O'yinlar uchun umumiy funksiya: yetmasa GameError('insufficient_stars')."""
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
            SELECT *,
                   GREATEST(0, CEIL(EXTRACT(EPOCH FROM
                       (free_case_used_at + make_interval(hours => %s) - NOW()))))::int
                       AS free_seconds_left
              FROM users WHERE telegram_id = %s
            """,
            (cooldown_h, telegram_id),
        )
        row = dict(cur.fetchone())
        row["free_seconds_left"] = row["free_seconds_left"] or 0
        return row


def set_steam_url(telegram_id: int, url: str) -> None:
    with db() as cur:
        _ensure_user(cur, telegram_id)
        cur.execute("UPDATE users SET steam_trade_url = %s WHERE telegram_id = %s", (url, telegram_id))


# ── Case ochish ───────────────────────────────────────────────────────

def open_case(telegram_id: int, case: dict, qty: int, cooldown_h: int, pick) -> dict:
    """Case ochadi. `pick` — case_id bo'yicha sovg'a tanlaydigan funksiya."""
    is_free = case["price"] == 0
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
            balance = _change_balance(cur, telegram_id, -cost, "case_open", case["id"])
            if balance is None:
                raise GameError("insufficient_stars")

        results = []
        for _ in range(qty):
            prize = pick(case["id"])
            cur.execute(
                "INSERT INTO case_openings "
                "(telegram_id, case_id, prize_name, prize_image, prize_value, prize_rarity, was_free) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (telegram_id, case["id"], prize["name"], prize.get("image", ""),
                 prize["value"], prize["rarity"], is_free),
            )
            cur.execute(
                "INSERT INTO inventory (telegram_id, prize_name, prize_image, prize_value, prize_rarity) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (telegram_id, prize["name"], prize.get("image", ""), prize["value"], prize["rarity"]),
            )
            prize.pop("weight", None)
            results.append({**prize, "inventoryId": cur.fetchone()["id"]})

        return {"results": results, "wasFree": is_free, "totalCost": cost, "balance": balance}


# ── Inventar ──────────────────────────────────────────────────────────

def get_inventory(telegram_id: int) -> list[dict]:
    with db() as cur:
        cur.execute(
            "SELECT id, prize_name, prize_image, prize_value, prize_rarity, status, obtained_at "
            "FROM inventory WHERE telegram_id = %s AND status = 'active' "
            "ORDER BY obtained_at DESC LIMIT 100",
            (telegram_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def sell_reward(value: int) -> int:
    return max(1, value * SELL_RATE_PERCENT // 100)


def sell_item(telegram_id: int, inventory_id: int) -> dict:
    with db() as cur:
        cur.execute(
            "UPDATE inventory SET status = 'sold' "
            "WHERE id = %s AND telegram_id = %s AND status = 'active' RETURNING prize_value",
            (inventory_id, telegram_id),
        )
        row = cur.fetchone()
        if row is None:
            raise GameError("item_not_found")
        reward = sell_reward(row["prize_value"])
        balance = _change_balance(cur, telegram_id, reward, "sell", inventory_id)
        return {"reward": reward, "balance": balance}


# ── Steam'ga chiqarish ────────────────────────────────────────────────

def create_withdraw_request(telegram_id: int, inventory_id: int) -> dict:
    with db() as cur:
        cur.execute("SELECT steam_trade_url FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cur.fetchone()
        if not user or not user["steam_trade_url"]:
            raise GameError("no_steam_url")
        cur.execute(
            "UPDATE inventory SET status = 'withdraw_pending' "
            "WHERE id = %s AND telegram_id = %s AND status = 'active' RETURNING *",
            (inventory_id, telegram_id),
        )
        item = cur.fetchone()
        if item is None:
            raise GameError("item_not_found")
        cur.execute(
            "INSERT INTO withdraw_requests "
            "(telegram_id, inventory_id, prize_name, prize_image, steam_trade_url) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (telegram_id, inventory_id, item["prize_name"], item["prize_image"] or "",
             user["steam_trade_url"]),
        )
        return dict(cur.fetchone())


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
    """So'rovni rad etadi va skinni foydalanuvchi inventariga qaytaradi."""
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


# ── To'lovlar ─────────────────────────────────────────────────────────

def save_payment(telegram_id: int, paid_stars: int, credit_stars: int,
                 charge_id: str, package: str, username=None, first_name=None) -> int | None:
    """To'lovni yozadi va balansni to'ldiradi.
    Shu charge_id avval qayd etilgan bo'lsa (Telegram qayta yuborgan) — None."""
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
    """Faqat yangi foydalanuvchi uchun chaqiriladi. Muvaffaqiyatli bo'lsa True."""
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


def referral_count(telegram_id: int) -> int:
    with db() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = %s", (telegram_id,))
        return cur.fetchone()["cnt"]


# ── Profil va reyting ─────────────────────────────────────────────────

def get_profile(telegram_id: int, username=None, first_name=None) -> dict:
    with db() as cur:
        user, _ = _ensure_user(cur, telegram_id, username, first_name)
        cur.execute(
            "SELECT COUNT(*) AS wins, COALESCE(SUM(prize_value), 0) AS total_value "
            "FROM case_openings WHERE telegram_id = %s",
            (telegram_id,),
        )
        stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = %s", (telegram_id,))
        refs = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT GREATEST(1, (NOW()::date - created_at::date) + 1) AS days "
            "FROM users WHERE telegram_id = %s",
            (telegram_id,),
        )
        days = cur.fetchone()["days"]
        return {**user, "wins": stats["wins"], "total_value": int(stats["total_value"]),
                "referrals": refs, "days": days}


def get_leaderboard(limit: int = 10) -> list[dict]:
    with db() as cur:
        cur.execute(
            """
            SELECT u.username,
                   SUM(c.prize_value)::bigint AS "totalValue",
                   COUNT(c.id)                AS wins
              FROM case_openings c
              JOIN users u ON u.telegram_id = c.telegram_id
             GROUP BY u.telegram_id, u.username
             ORDER BY "totalValue" DESC
             LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
