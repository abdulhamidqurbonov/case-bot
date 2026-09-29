import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """Jadvallarni yaratish — birinchi ishga tushganda"""
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        telegram_id        BIGINT PRIMARY KEY,
        username           TEXT,
        first_name         TEXT,
        stars_balance      INTEGER DEFAULT 0,
        premium_cases      INTEGER DEFAULT 0,
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
        id                         BIGSERIAL PRIMARY KEY,
        telegram_id                BIGINT REFERENCES users(telegram_id),
        stars_amount               INTEGER NOT NULL,
        cases_granted              INTEGER NOT NULL,
        telegram_charge_id         TEXT UNIQUE,
        created_at                 TIMESTAMPTZ DEFAULT NOW()
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
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("✅ Baza tayyor")
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            if row:
                if username and row.get("username") != username:
                    cur.execute(
                        "UPDATE users SET username=%s, first_name=%s WHERE telegram_id=%s",
                        (username, first_name, telegram_id)
                    )
                    conn.commit()
                    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                    row = cur.fetchone()
                return dict(row)

            cur.execute(
                "INSERT INTO users (telegram_id, username, first_name) VALUES (%s,%s,%s)",
                (telegram_id, username, first_name)
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
            return dict(cur.fetchone())
    finally:
        conn.close()


def set_steam_url(telegram_id: int, url: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET steam_trade_url=%s WHERE telegram_id=%s", (url, telegram_id))
        conn.commit()
    finally:
        conn.close()


# ── Case openings ─────────────────────────────────────────────────────

def save_opening(telegram_id: int, case_id: str, prize: dict, was_free: bool) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_openings (telegram_id,case_id,prize_name,prize_image,prize_value,prize_rarity,was_free)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (telegram_id, case_id, prize["name"], prize.get("image",""),
                 prize["value"], prize["rarity"], was_free)
            )
            cur.execute(
                "INSERT INTO inventory (telegram_id,prize_name,prize_image,prize_value,prize_rarity)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (telegram_id, prize["name"], prize.get("image",""),
                 prize["value"], prize["rarity"])
            )
            inv = dict(cur.fetchone())
        conn.commit()
        return inv
    finally:
        conn.close()


def update_free_case_time(telegram_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET free_case_used_at=%s WHERE telegram_id=%s",
                (datetime.now(timezone.utc), telegram_id)
            )
        conn.commit()
    finally:
        conn.close()


# ── Inventory ─────────────────────────────────────────────────────────

def get_inventory(telegram_id: int) -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM inventory WHERE telegram_id=%s AND status='active'"
                " ORDER BY obtained_at DESC LIMIT 50",
                (telegram_id,)
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def sell_item(inventory_id: int, telegram_id: int) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM inventory WHERE id=%s", (inventory_id,))
            row = cur.fetchone()
            if not row or row["telegram_id"] != telegram_id or row["status"] != "active":
                return 0
            reward = max(1, row["prize_value"] // 10)
            cur.execute("UPDATE inventory SET status='sold' WHERE id=%s", (inventory_id,))
            cur.execute(
                "UPDATE users SET stars_balance=stars_balance+%s WHERE telegram_id=%s",
                (reward, telegram_id)
            )
        conn.commit()
        return reward
    finally:
        conn.close()


# ── Withdraw ──────────────────────────────────────────────────────────

def create_withdraw_request(telegram_id: int, inventory_id: int) -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM inventory WHERE id=%s", (inventory_id,))
            item = cur.fetchone()
            if not item or item["telegram_id"] != telegram_id or item["status"] != "active":
                return None

            cur.execute("SELECT steam_trade_url FROM users WHERE telegram_id=%s", (telegram_id,))
            user = cur.fetchone()
            if not user or not user["steam_trade_url"]:
                return None

            cur.execute("UPDATE inventory SET status='withdraw_pending' WHERE id=%s", (inventory_id,))
            cur.execute(
                "INSERT INTO withdraw_requests (telegram_id,inventory_id,prize_name,prize_image,steam_trade_url)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (telegram_id, inventory_id, item["prize_name"],
                 item.get("prize_image",""), user["steam_trade_url"])
            )
            req = dict(cur.fetchone())
        conn.commit()
        return req
    finally:
        conn.close()


def confirm_withdraw(req_id: int) -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM withdraw_requests WHERE id=%s", (req_id,))
            req = cur.fetchone()
            if not req:
                return None
            cur.execute(
                "UPDATE withdraw_requests SET status='sent', processed_at=%s WHERE id=%s",
                (datetime.now(timezone.utc), req_id)
            )
            cur.execute("UPDATE inventory SET status='withdrawn' WHERE id=%s", (req["inventory_id"],))
        conn.commit()
        return dict(req)
    finally:
        conn.close()


# ── Payments ──────────────────────────────────────────────────────────

def save_payment(telegram_id: int, stars: int, cases: int, charge_id: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO payments (telegram_id,stars_amount,cases_granted,telegram_charge_id)"
                " VALUES (%s,%s,%s,%s) ON CONFLICT (telegram_charge_id) DO NOTHING",
                (telegram_id, stars, cases, charge_id)
            )
            cur.execute(
                "UPDATE users SET premium_cases=premium_cases+%s, stars_balance=stars_balance+%s"
                " WHERE telegram_id=%s",
                (cases, stars, telegram_id)
            )
        conn.commit()
    finally:
        conn.close()


# ── Tasks ─────────────────────────────────────────────────────────────

def get_completed_tasks(telegram_id: int) -> set:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT task_key FROM tasks_completed WHERE telegram_id=%s", (telegram_id,))
            return {r["task_key"] for r in cur.fetchall()}
    finally:
        conn.close()


def complete_task(telegram_id: int, task_key: str, reward_cases: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks_completed (telegram_id,task_key,reward_cases)"
                " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (telegram_id, task_key, reward_cases)
            )
            cur.execute(
                "UPDATE users SET premium_cases=premium_cases+%s WHERE telegram_id=%s",
                (reward_cases, telegram_id)
            )
        conn.commit()
    finally:
        conn.close()


# ── Leaderboard ───────────────────────────────────────────────────────

def get_leaderboard() -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.telegram_id as "telegramId",
                       u.username,
                       COALESCE(SUM(c.prize_value),0) as "totalValue",
                       COUNT(c.id) as wins
                FROM users u
                LEFT JOIN case_openings c ON c.telegram_id = u.telegram_id
                GROUP BY u.telegram_id, u.username
                HAVING COALESCE(SUM(c.prize_value),0) > 0
                ORDER BY "totalValue" DESC
                LIMIT 10
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()