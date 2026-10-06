-- CS2 Cases Bot — baza sxemasi
-- Server ishga tushganda bu jadvallarni O'ZI yaratadi. Qo'lda ishga tushirish shart emas.

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_referrals_referred ON referrals(referred_id);
CREATE INDEX IF NOT EXISTS idx_openings_user   ON case_openings(telegram_id);
CREATE INDEX IF NOT EXISTS idx_inventory_user  ON inventory(telegram_id, status);
CREATE INDEX IF NOT EXISTS idx_inventory_time  ON inventory(obtained_at DESC);
CREATE INDEX IF NOT EXISTS idx_withdraw_status ON withdraw_requests(status);
CREATE INDEX IF NOT EXISTS idx_tasks_user      ON tasks_completed(telegram_id);
CREATE INDEX IF NOT EXISTS idx_referrer        ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_balance_log     ON balance_log(telegram_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_games_user      ON games(telegram_id, created_at DESC);
