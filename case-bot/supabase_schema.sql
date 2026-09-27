-- ============================================================
--  CS2 BOT — Supabase Schema
--  Supabase dashboard > SQL Editor ga copy-paste qiling
-- ============================================================

-- Foydalanuvchilar
CREATE TABLE IF NOT EXISTS users (
    telegram_id         BIGINT PRIMARY KEY,
    username            TEXT,
    first_name          TEXT,
    stars_balance       INTEGER DEFAULT 0,
    premium_cases       INTEGER DEFAULT 0,
    free_case_used_at   TIMESTAMPTZ,
    steam_trade_url     TEXT,
    referred_by         BIGINT REFERENCES users(telegram_id),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Case ochish tarixi
CREATE TABLE IF NOT EXISTS case_openings (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id),
    case_id         TEXT NOT NULL,
    prize_name      TEXT NOT NULL,
    prize_image     TEXT,
    prize_value     INTEGER NOT NULL,
    prize_rarity    TEXT NOT NULL,
    was_free        BOOLEAN DEFAULT FALSE,
    opened_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Inventar (yutilgan skinlar)
CREATE TABLE IF NOT EXISTS inventory (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id),
    prize_name      TEXT NOT NULL,
    prize_image     TEXT,
    prize_value     INTEGER NOT NULL,
    prize_rarity    TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    -- status: active | sold | withdraw_pending | withdrawn
    obtained_at     TIMESTAMPTZ DEFAULT NOW()
);

-- To'lov tarixi (Stars)
CREATE TABLE IF NOT EXISTS payments (
    id                          BIGSERIAL PRIMARY KEY,
    telegram_id                 BIGINT REFERENCES users(telegram_id),
    stars_amount                INTEGER NOT NULL,
    cases_granted               INTEGER NOT NULL,
    telegram_charge_id          TEXT UNIQUE,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);

-- Steam chiqarish so'rovlari
CREATE TABLE IF NOT EXISTS withdraw_requests (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id),
    inventory_id    BIGINT REFERENCES inventory(id),
    prize_name      TEXT NOT NULL,
    prize_image     TEXT,
    steam_trade_url TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    -- status: pending | sent | rejected
    admin_note      TEXT,
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

-- Vazifalar (bajarilgan)
CREATE TABLE IF NOT EXISTS tasks_completed (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT REFERENCES users(telegram_id),
    task_key        TEXT NOT NULL,
    reward_cases    INTEGER DEFAULT 0,
    completed_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(telegram_id, task_key)
);

-- Referal hisobi
CREATE TABLE IF NOT EXISTS referrals (
    id              BIGSERIAL PRIMARY KEY,
    referrer_id     BIGINT REFERENCES users(telegram_id),
    referred_id     BIGINT REFERENCES users(telegram_id),
    reward_given    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indekslar
CREATE INDEX IF NOT EXISTS idx_openings_user   ON case_openings(telegram_id);
CREATE INDEX IF NOT EXISTS idx_inventory_user  ON inventory(telegram_id, status);
CREATE INDEX IF NOT EXISTS idx_withdraw_status ON withdraw_requests(status);
CREATE INDEX IF NOT EXISTS idx_tasks_user      ON tasks_completed(telegram_id);
