require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const crypto = require('crypto');
const { Telegraf } = require('telegraf');
const { db, getOrCreateUser } = require('./db');
const { pickPrize } = require('./prizes');

const BOT_TOKEN = process.env.BOT_TOKEN;
const WEBAPP_URL = process.env.WEBAPP_URL; // masalan https://sizning-domen.com
const PORT = process.env.PORT || 3000;
const FREE_CASE_COOLDOWN_SEC = 24 * 60 * 60; // 24 soat
const CHANNEL_USERNAME = process.env.CHANNEL_USERNAME || null; // masalan @mening_kanalim
const TASK_REWARD_CASES = parseInt(process.env.TASK_REWARD_CASES || '1', 10);
let BOT_USERNAME = process.env.BOT_USERNAME || null; // referal havolalar uchun

if (!BOT_TOKEN) {
  console.error('XATOLIK: .env faylida BOT_TOKEN ko\'rsatilmagan');
  process.exit(1);
}

const bot = new Telegraf(BOT_TOKEN);
const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

// Bot username'ni avtomatik aniqlash (referal havolalar uchun kerak)
bot.telegram.getMe().then((me) => {
  if (!BOT_USERNAME) BOT_USERNAME = me.username;
  console.log(`Bot username: @${BOT_USERNAME}`);
}).catch((err) => console.error('getMe xato:', err.message));

// --- Telegram initData ni tekshirish (xavfsizlik uchun MAJBURIY) ---
function verifyInitData(initData) {
  const params = new URLSearchParams(initData);
  const hash = params.get('hash');
  params.delete('hash');
  const dataCheckArr = [];
  for (const [key, value] of [...params.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    dataCheckArr.push(`${key}=${value}`);
  }
  const dataCheckString = dataCheckArr.join('\n');
  const secretKey = crypto.createHmac('sha256', 'WebAppData').update(BOT_TOKEN).digest();
  const computedHash = crypto.createHmac('sha256', secretKey).update(dataCheckString).digest('hex');
  if (computedHash !== hash) return null;
  const userJson = params.get('user');
  return userJson ? JSON.parse(userJson) : null;
}

// --- API: foydalanuvchi holatini olish ---
app.post('/api/me', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const dbUser = getOrCreateUser(user.id, user.username);
  res.json({
    telegramId: dbUser.telegram_id,
    freeCasesLeft: dbUser.free_cases_left,
    premiumCases: dbUser.premium_cases,
    canOpenFreeAt: dbUser.last_free_case_at + FREE_CASE_COOLDOWN_SEC,
  });
});

// --- API: case ochish ---
app.post('/api/open-case', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const dbUser = getOrCreateUser(user.id, user.username);
  const now = Math.floor(Date.now() / 1000);
  const usePremium = req.body.usePremium === true;

  if (usePremium) {
    if (dbUser.premium_cases < 1) return res.status(400).json({ error: 'no_premium_cases' });
    db.prepare('UPDATE users SET premium_cases = premium_cases - 1 WHERE telegram_id = ?').run(user.id);
  } else {
    const canOpen = dbUser.free_cases_left > 0 || (now - dbUser.last_free_case_at) >= FREE_CASE_COOLDOWN_SEC;
    if (!canOpen) return res.status(400).json({ error: 'free_case_on_cooldown' });
    db.prepare('UPDATE users SET free_cases_left = 0, last_free_case_at = ? WHERE telegram_id = ?').run(now, user.id);
  }

  const prize = pickPrize(usePremium);
  db.prepare('INSERT INTO case_openings (telegram_id, prize_name, prize_value, was_premium) VALUES (?, ?, ?, ?)')
    .run(user.id, prize.name, prize.value, usePremium ? 1 : 0);

  res.json({ prize });
});

// --- API: inventar (yutilgan sovg'alar) ---
app.post('/api/inventory', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const items = db.prepare(`
    SELECT prize_name as name, prize_value as value, was_premium as wasPremium, opened_at as openedAt
    FROM case_openings WHERE telegram_id = ? ORDER BY opened_at DESC LIMIT 100
  `).all(user.id);
  res.json({ items });
});

// --- API: referal havola va statistikasi ---
app.post('/api/referral', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  getOrCreateUser(user.id, user.username);
  const referrals = db.prepare('SELECT COUNT(*) as count FROM users WHERE referred_by = ?').get(user.id);
  const link = BOT_USERNAME ? `https://t.me/${BOT_USERNAME}?start=ref_${user.id}` : null;
  res.json({ link, referralCount: referrals.count });
});

// --- API: vazifalar ro'yxati va holati ---
app.post('/api/tasks', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const completed = db.prepare('SELECT task_key FROM tasks_completed WHERE telegram_id = ?').all(user.id).map(r => r.task_key);
  const tasks = [];
  if (CHANNEL_USERNAME) {
    tasks.push({
      id: 'join_channel',
      title: `Kanalga obuna bo'ling`,
      subtitle: CHANNEL_USERNAME,
      reward: TASK_REWARD_CASES,
      completed: completed.includes('join_channel'),
      channelUsername: CHANNEL_USERNAME,
    });
  }
  res.json({ tasks });
});

// --- API: vazifani tekshirish va mukofot berish ---
app.post('/api/tasks/check', async (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const taskId = req.body.taskId;
  if (taskId !== 'join_channel' || !CHANNEL_USERNAME) {
    return res.status(400).json({ error: 'unknown_task' });
  }

  const already = db.prepare('SELECT 1 FROM tasks_completed WHERE telegram_id = ? AND task_key = ?').get(user.id, 'join_channel');
  if (already) return res.status(400).json({ error: 'already_completed' });

  try {
    const member = await bot.telegram.getChatMember(CHANNEL_USERNAME, user.id);
    const isMember = ['member', 'administrator', 'creator'].includes(member.status);
    if (!isMember) return res.status(400).json({ error: 'not_member' });

    getOrCreateUser(user.id, user.username);
    db.prepare('INSERT INTO tasks_completed (telegram_id, task_key) VALUES (?, ?)').run(user.id, 'join_channel');
    db.prepare('UPDATE users SET premium_cases = premium_cases + ? WHERE telegram_id = ?').run(TASK_REWARD_CASES, user.id);

    res.json({ success: true, reward: TASK_REWARD_CASES });
  } catch (err) {
    console.error('Kanal tekshiruvida xato:', err.message);
    res.status(500).json({ error: 'check_failed' });
  }
});

// --- API: reyting (leaderboard) ---
app.get('/api/leaderboard', (req, res) => {
  const rows = db.prepare(`
    SELECT u.telegram_id as telegramId, u.username,
           COALESCE(SUM(c.prize_value), 0) as totalValue,
           COUNT(c.id) as wins
    FROM users u
    LEFT JOIN case_openings c ON c.telegram_id = u.telegram_id
    GROUP BY u.telegram_id
    HAVING totalValue > 0
    ORDER BY totalValue DESC
    LIMIT 10
  `).all();
  res.json({ leaderboard: rows });
});

// --- API: profil statistikasi ---
app.post('/api/profile', (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const dbUser = getOrCreateUser(user.id, user.username);
  const stats = db.prepare(`
    SELECT COUNT(*) as wins, COALESCE(SUM(prize_value), 0) as totalValue
    FROM case_openings WHERE telegram_id = ?
  `).get(user.id);
  const referrals = db.prepare('SELECT COUNT(*) as count FROM users WHERE referred_by = ?').get(user.id);
  const daysWithUs = Math.max(1, Math.floor((Date.now() / 1000 - dbUser.created_at) / 86400) + 1);

  res.json({
    username: user.username || dbUser.username,
    firstName: user.first_name || '',
    wins: stats.wins,
    totalValue: stats.totalValue,
    referrals: referrals.count,
    daysWithUs,
  });
});

// --- API: Stars invoice yaratish (premium case sotib olish) ---
const STARS_PACKAGES = {
  small: { stars: 50, cases: 3, label: '3 ta Premium Case' },
  medium: { stars: 150, cases: 10, label: '10 ta Premium Case' },
  large: { stars: 500, cases: 40, label: '40 ta Premium Case' },
};

app.post('/api/create-invoice', async (req, res) => {
  const user = verifyInitData(req.body.initData || '');
  if (!user) return res.status(401).json({ error: 'invalid_init_data' });

  const pkg = STARS_PACKAGES[req.body.package];
  if (!pkg) return res.status(400).json({ error: 'unknown_package' });

  try {
    const link = await bot.telegram.createInvoiceLink({
      title: pkg.label,
      description: `${pkg.cases} ta Premium Case sotib olasiz`,
      payload: JSON.stringify({ telegramId: user.id, package: req.body.package }),
      provider_token: '', // Stars uchun bo'sh qoldiriladi
      currency: 'XTR',
      prices: [{ label: pkg.label, amount: pkg.stars }],
    });
    res.json({ invoiceLink: link });
  } catch (err) {
    console.error('Invoice yaratishda xato:', err);
    res.status(500).json({ error: 'invoice_creation_failed' });
  }
});

// --- Bot: to'lovdan oldingi tekshiruv (majburiy javob berish kerak) ---
bot.on('pre_checkout_query', (ctx) => {
  ctx.answerPreCheckoutQuery(true).catch(console.error);
});

// --- Bot: muvaffaqiyatli to'lov ---
bot.on('message', (ctx, next) => {
  const payment = ctx.message?.successful_payment;
  if (payment) {
    const payload = JSON.parse(payment.invoice_payload);
    const pkg = STARS_PACKAGES[payload.package];
    if (pkg) {
      getOrCreateUser(payload.telegramId, ctx.from.username);
      db.prepare('UPDATE users SET premium_cases = premium_cases + ? WHERE telegram_id = ?')
        .run(pkg.cases, payload.telegramId);
      db.prepare('INSERT INTO payments (telegram_id, stars_amount, cases_granted, telegram_payment_charge_id) VALUES (?, ?, ?, ?)')
        .run(payload.telegramId, payment.total_amount, pkg.cases, payment.telegram_payment_charge_id);
      ctx.reply(`✅ Rahmat! ${pkg.cases} ta Premium Case hisobingizga qo'shildi. Mini App'ni oching va oching!`);
    }
    return;
  }
  return next();
});

// --- Bot: /start komandasi ---
bot.start((ctx) => {
  const refMatch = ctx.message.text.match(/ref_(\d+)/);
  const referredBy = refMatch ? parseInt(refMatch[1]) : null;
  getOrCreateUser(ctx.from.id, ctx.from.username, referredBy);

  ctx.reply(
    '🎁 Xush kelibsiz! Bepul kейsni oching va sovg\'a yutib oling!',
    {
      reply_markup: {
        inline_keyboard: [[{ text: '🎁 Case Ochish', web_app: { url: WEBAPP_URL } }]],
      },
    }
  );
});

bot.launch();
app.listen(PORT, () => console.log(`Server ${PORT}-portda ishlamoqda`));

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
