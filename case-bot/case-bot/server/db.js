const Database = require('better-sqlite3');
const path = require('path');

const db = new Database(path.join(__dirname, '..', 'data.db'));
db.pragma('journal_mode = WAL');

// Foydalanuvchilar jadvali
db.exec(`
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  username TEXT,
  free_cases_left INTEGER DEFAULT 1,
  premium_cases INTEGER DEFAULT 0,
  last_free_case_at INTEGER DEFAULT 0,
  referred_by INTEGER,
  created_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS case_openings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER,
  prize_name TEXT,
  prize_value INTEGER,
  was_premium INTEGER DEFAULT 0,
  opened_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER,
  stars_amount INTEGER,
  cases_granted INTEGER,
  telegram_payment_charge_id TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS tasks_completed (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER,
  task_key TEXT,
  completed_at INTEGER DEFAULT (strftime('%s','now')),
  UNIQUE(telegram_id, task_key)
);
`);

function getOrCreateUser(telegramId, username, referredBy) {
  let user = db.prepare('SELECT * FROM users WHERE telegram_id = ?').get(telegramId);
  if (!user) {
    db.prepare('INSERT INTO users (telegram_id, username, referred_by) VALUES (?, ?, ?)')
      .run(telegramId, username || null, referredBy || null);
    user = db.prepare('SELECT * FROM users WHERE telegram_id = ?').get(telegramId);
  }
  return user;
}

module.exports = { db, getOrCreateUser };
