"""Admin AI uchun FAQAT O'QIYDIGAN tahlil so'rovlari.

Bu yerdagi hech bir funksiya balans, inventar yoki sozlamalarni o'zgartirmaydi.
Natijalar oddiy dict/list — AI'ga JSON qilib beriladi.
"""
import threading
import time

from app.database import db

# ── Kim hozir ilovada (xotirada; server qayta ishga tushsa noldan boshlanadi) ──

_presence: dict[int, tuple[float, str | None]] = {}
_plock = threading.Lock()

SCREEN_NAMES = {
    "cases": "Case'lar ro'yxati", "case": "case ochish sahifasi", "games": "O'yinlar ro'yxati",
    "upgrade": "Upgrade o'yini", "contract": "Shartnoma o'yini", "crash": "Crash (samolyot) o'yini",
    "dice": "Dice o'yini", "inv": "Inventar", "prof": "Profil", "shop": "Balans to'ldirish oynasi",
    "support": "Yordam (AI) chati",
}


def seen(uid: int, screen: str | None = None) -> None:
    with _plock:
        old = _presence.get(uid)
        _presence[uid] = (time.time(), screen if screen else (old[1] if old else None))
        if len(_presence) > 20000:                       # xotira o'smasligi uchun eskilarni tozalaymiz
            cut = time.time() - 3600
            for k in [k for k, v in _presence.items() if v[0] < cut]:
                _presence.pop(k, None)


def presence_of(uid: int) -> dict | None:
    v = _presence.get(uid)
    if not v:
        return None
    return {"seconds_ago": int(time.time() - v[0]), "screen": SCREEN_NAMES.get(v[1] or "", v[1])}


def _online(minutes: int) -> dict[int, tuple[float, str | None]]:
    cut = time.time() - minutes * 60
    with _plock:
        return {k: v for k, v in _presence.items() if v[0] >= cut}


# ── Yordamchilar ──────────────────────────────────────────────────────

def _rows(sql: str, args=()) -> list[dict]:
    with db() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def _one(sql: str, args=()) -> dict:
    with db() as cur:
        cur.execute(sql, args)
        r = cur.fetchone()
        return dict(r) if r else {}


def _days(d) -> int:
    try:
        return max(1, min(90, int(d)))
    except (TypeError, ValueError):
        return 7


def _limit(n, default=10, top=50) -> int:
    try:
        return max(1, min(top, int(n)))
    except (TypeError, ValueError):
        return default


# ── Umumiy ko'rsatkichlar ─────────────────────────────────────────────

def overview(days: int = 7) -> dict:
    d = _days(days)
    totals = _one("""
        SELECT
          (SELECT COUNT(*) FROM users) AS users_total,
          (SELECT COUNT(*) FROM users WHERE created_at > NOW() - make_interval(days => %(d)s)) AS new_users,
          (SELECT COUNT(DISTINCT telegram_id) FROM balance_log WHERE created_at > NOW() - make_interval(days => %(d)s)) AS active_players,
          (SELECT COUNT(*) FROM users WHERE last_seen_at > NOW() - make_interval(days => %(d)s)) AS opened_app,
          (SELECT COUNT(*) FROM payments WHERE created_at > NOW() - make_interval(days => %(d)s)) AS payments,
          (SELECT COALESCE(SUM(stars_amount),0) FROM payments WHERE created_at > NOW() - make_interval(days => %(d)s))::bigint AS stars_paid,
          (SELECT COUNT(DISTINCT telegram_id) FROM payments WHERE created_at > NOW() - make_interval(days => %(d)s)) AS payers,
          (SELECT COUNT(DISTINCT telegram_id) FROM payments) AS payers_all_time,
          (SELECT COALESCE(SUM(stars_amount),0) FROM payments)::bigint AS stars_paid_all_time,
          (SELECT COUNT(*) FROM referrals WHERE created_at > NOW() - make_interval(days => %(d)s)) AS referrals,
          (SELECT COUNT(*) FROM case_openings WHERE opened_at > NOW() - make_interval(days => %(d)s)) AS case_openings,
          (SELECT COUNT(*) FROM games WHERE created_at > NOW() - make_interval(days => %(d)s)) AS games_played,
          (SELECT COALESCE(SUM(stars_balance),0) FROM users)::bigint AS stars_on_balances,
          (SELECT COALESCE(SUM(prize_value),0) FROM inventory WHERE status='active')::bigint AS skins_in_inventories,
          (SELECT COUNT(*) FROM withdraw_requests WHERE status='pending') AS withdraw_pending
    """, {"d": d})
    daily = _rows("""
        WITH days AS (SELECT generate_series((NOW() AT TIME ZONE 'Asia/Tashkent')::date - (%(d)s - 1),
                                             (NOW() AT TIME ZONE 'Asia/Tashkent')::date, '1 day')::date AS day)
        SELECT to_char(days.day, 'YYYY-MM-DD') AS day,
          (SELECT COUNT(*) FROM users u WHERE (u.created_at AT TIME ZONE 'Asia/Tashkent')::date = days.day) AS new_users,
          (SELECT COUNT(DISTINCT b.telegram_id) FROM balance_log b
             WHERE (b.created_at AT TIME ZONE 'Asia/Tashkent')::date = days.day) AS active_players,
          (SELECT COALESCE(SUM(p.stars_amount),0) FROM payments p
             WHERE (p.created_at AT TIME ZONE 'Asia/Tashkent')::date = days.day)::bigint AS stars_paid,
          (SELECT COUNT(*) FROM games g WHERE (g.created_at AT TIME ZONE 'Asia/Tashkent')::date = days.day) AS games,
          (SELECT COUNT(*) FROM case_openings c WHERE (c.opened_at AT TIME ZONE 'Asia/Tashkent')::date = days.day) AS cases_opened
        FROM days ORDER BY days.day
    """, {"d": min(d, 31)})
    returning = _one("""
        SELECT COUNT(*) FILTER (WHERE created_at < NOW() - INTERVAL '1 day') AS old_enough,
               COUNT(*) FILTER (WHERE created_at < NOW() - INTERVAL '1 day'
                                  AND last_seen_at > created_at + INTERVAL '1 day') AS came_back_next_day
          FROM users WHERE created_at > NOW() - make_interval(days => %(d)s)
    """, {"d": max(d, 2)})
    return {"period_days": d, "totals": totals, "daily": daily, "retention": returning,
            "online_now": len(_online(5))}


def game_economy(days: int = 7) -> dict:
    d = _days(days)
    games = _rows("""
        SELECT game, COUNT(*) AS rounds, COUNT(DISTINCT telegram_id) AS players,
               SUM(bet)::bigint AS total_bet, SUM(payout)::bigint AS total_paid,
               (SUM(bet) - SUM(payout))::bigint AS house_profit,
               ROUND(100.0 * SUM(payout) / NULLIF(SUM(bet),0), 1) AS real_rtp_percent
          FROM games WHERE created_at > NOW() - make_interval(days => %s)
         GROUP BY game ORDER BY rounds DESC
    """, (d,))
    cases = _rows("""
        SELECT c.case_id, COUNT(*) AS opened, COUNT(DISTINCT c.telegram_id) AS players,
               SUM(c.prize_value)::bigint AS prizes_value, COUNT(*) FILTER (WHERE c.was_free) AS free_opens,
               COALESCE((SELECT -SUM(b.delta) FROM balance_log b WHERE b.reason='case_open' AND b.ref=c.case_id
                         AND b.created_at > NOW() - make_interval(days => %(d)s)),0)::bigint AS stars_spent
          FROM case_openings c WHERE c.opened_at > NOW() - make_interval(days => %(d)s)
         GROUP BY c.case_id ORDER BY opened DESC
    """, {"d": d})
    return {"period_days": d, "games": games, "cases": cases}


# ── Foydalanuvchilar ──────────────────────────────────────────────────

def find_user(query: str) -> list[dict]:
    q = (query or "").strip().lstrip("@")
    if not q:
        return []
    if q.isdigit():
        return _rows("SELECT telegram_id, username, first_name, created_at, last_seen_at FROM users "
                     "WHERE telegram_id = %s", (int(q),))
    exact = _rows("SELECT telegram_id, username, first_name, created_at, last_seen_at FROM users "
                  "WHERE LOWER(username) = LOWER(%s) LIMIT 5", (q,))
    if exact:
        return exact
    like = "%" + q.replace("%", "").replace("_", r"\_") + "%"
    return _rows("SELECT telegram_id, username, first_name, created_at, last_seen_at FROM users "
                 "WHERE username ILIKE %s OR first_name ILIKE %s ORDER BY last_seen_at DESC NULLS LAST LIMIT 10",
                 (like, like))


def user_report(user: str) -> dict:
    """Bitta o'yinchi haqida to'liq ma'lumot: hozir nima qilyapti, pul harakati, xatolari."""
    found = find_user(str(user))
    if not found:
        return {"error": "user_not_found", "query": user}
    if len(found) > 1 and not str(user).strip().lstrip("@").isdigit():
        return {"error": "several_matches", "matches": found}
    uid = found[0]["telegram_id"]
    u = _one("""
        SELECT u.telegram_id, u.username, u.first_name, u.stars_balance, u.created_at, u.last_seen_at,
               u.referred_by, (u.steam_trade_url IS NOT NULL) AS steam_url_set, u.steam_name,
               u.free_case_used_at,
               (SELECT COALESCE(SUM(stars_amount),0) FROM payments p WHERE p.telegram_id=u.telegram_id)::bigint AS total_paid_stars,
               (SELECT COUNT(*) FROM payments p WHERE p.telegram_id=u.telegram_id) AS payments_count,
               (SELECT MAX(created_at) FROM payments p WHERE p.telegram_id=u.telegram_id) AS last_payment_at,
               (SELECT COUNT(*) FROM referrals r WHERE r.referrer_id=u.telegram_id) AS invited_friends,
               (SELECT COUNT(*) FROM case_openings c WHERE c.telegram_id=u.telegram_id) AS cases_opened,
               (SELECT COUNT(*) FROM games g WHERE g.telegram_id=u.telegram_id) AS games_played,
               (SELECT COALESCE(SUM(bet)-SUM(payout),0) FROM games g WHERE g.telegram_id=u.telegram_id)::bigint AS lost_in_games,
               (SELECT COUNT(*) FROM inventory i WHERE i.telegram_id=u.telegram_id AND i.status='active') AS skins_now,
               (SELECT COALESCE(SUM(prize_value),0) FROM inventory i WHERE i.telegram_id=u.telegram_id AND i.status='active')::bigint AS skins_value_now,
               (SELECT MAX(created_at) FROM balance_log b WHERE b.telegram_id=u.telegram_id) AS last_money_action_at
          FROM users u WHERE u.telegram_id = %s
    """, (uid,))
    timeline = _rows("""
        SELECT created_at AS at, reason AS action, delta AS stars_change, balance AS balance_after, ref
          FROM balance_log WHERE telegram_id = %s ORDER BY id DESC LIMIT 25
    """, (uid,))
    games = _rows("""
        SELECT created_at AS at, game, bet, payout, win FROM games WHERE telegram_id = %s ORDER BY id DESC LIMIT 15
    """, (uid,))
    best = _rows("""
        SELECT prize_name, prize_value, source, status, obtained_at FROM inventory WHERE telegram_id = %s
         ORDER BY prize_value DESC LIMIT 5
    """, (uid,))
    withdrawals = _rows("""
        SELECT id, prize_name, status, requested_at, admin_note FROM withdraw_requests
         WHERE telegram_id = %s ORDER BY id DESC LIMIT 5
    """, (uid,))
    errors = _rows("""
        SELECT created_at AS at, code, detail FROM user_events WHERE telegram_id = %s AND kind='error'
         ORDER BY id DESC LIMIT 12
    """, (uid,))
    support = _rows("""
        SELECT created_at AS at, role, LEFT(content, 300) AS text FROM ai_messages
         WHERE scope='support' AND telegram_id = %s ORDER BY id DESC LIMIT 8
    """, (uid,))
    return {"user": u, "in_app_now": presence_of(uid), "recent_money_actions": timeline,
            "recent_games": games, "best_skins": best, "withdrawals": withdrawals,
            "recent_errors": errors, "recent_support_chat": support}


def top_users(metric: str = "paid", days: int = 7, limit: int = 10) -> dict:
    d, n = _days(days), _limit(limit)
    queries = {
        "paid": """SELECT u.telegram_id, u.username, u.first_name, SUM(p.stars_amount)::bigint AS value
                     FROM payments p JOIN users u USING (telegram_id)
                    WHERE p.created_at > NOW() - make_interval(days => %s)
                    GROUP BY u.telegram_id ORDER BY value DESC LIMIT %s""",
        "active": """SELECT u.telegram_id, u.username, u.first_name, COUNT(*) AS value
                       FROM balance_log b JOIN users u USING (telegram_id)
                      WHERE b.created_at > NOW() - make_interval(days => %s)
                      GROUP BY u.telegram_id ORDER BY value DESC LIMIT %s""",
        "won": """SELECT u.telegram_id, u.username, u.first_name, (SUM(g.payout)-SUM(g.bet))::bigint AS value
                    FROM games g JOIN users u USING (telegram_id)
                   WHERE g.created_at > NOW() - make_interval(days => %s)
                   GROUP BY u.telegram_id ORDER BY value DESC LIMIT %s""",
        "lost": """SELECT u.telegram_id, u.username, u.first_name, (SUM(g.bet)-SUM(g.payout))::bigint AS value
                     FROM games g JOIN users u USING (telegram_id)
                    WHERE g.created_at > NOW() - make_interval(days => %s)
                    GROUP BY u.telegram_id ORDER BY value DESC LIMIT %s""",
        "referrals": """SELECT u.telegram_id, u.username, u.first_name, COUNT(*) AS value
                          FROM referrals r JOIN users u ON u.telegram_id = r.referrer_id
                         WHERE r.created_at > NOW() - make_interval(days => %s)
                         GROUP BY u.telegram_id ORDER BY value DESC LIMIT %s""",
        "balance": """SELECT telegram_id, username, first_name, stars_balance AS value FROM users
                       WHERE %s > 0 ORDER BY stars_balance DESC LIMIT %s""",
    }
    m = metric if metric in queries else "paid"
    return {"metric": m, "period_days": d, "users": _rows(queries[m], (d, n))}


def errors_report(hours: int = 24, limit: int = 30) -> dict:
    h = max(1, min(24 * 14, int(hours or 24)))
    by_code = _rows("""
        SELECT code, COUNT(*) AS times, COUNT(DISTINCT telegram_id) AS users, MAX(created_at) AS last_at
          FROM user_events WHERE kind='error' AND created_at > NOW() - make_interval(hours => %s)
         GROUP BY code ORDER BY times DESC LIMIT 20
    """, (h,))
    by_user = _rows("""
        SELECT e.telegram_id, u.username, u.first_name, COUNT(*) AS errors,
               STRING_AGG(DISTINCT e.code, ', ') AS codes, MAX(e.created_at) AS last_at
          FROM user_events e LEFT JOIN users u USING (telegram_id)
         WHERE e.kind='error' AND e.created_at > NOW() - make_interval(hours => %s)
         GROUP BY e.telegram_id, u.username, u.first_name ORDER BY errors DESC LIMIT %s
    """, (h, _limit(limit, 30)))
    return {"period_hours": h, "by_error_code": by_code, "by_user": by_user,
            "code_meanings": {
                "insufficient_stars": "balans yetmadi", "deposit_required": "Steam'ga chiqarish uchun to'lov yetmaydi",
                "withdraw_disabled": "chiqarish yopiq", "no_steam_url": "Trade URL kiritmagan",
                "invalid_url": "Trade URL noto'g'ri", "steam_not_found": "Steam akkaunt topilmadi",
                "network": "internet uzildi", "server_error": "server xatosi", "js": "ilovada JavaScript xato",
                "invoice_failed": "to'lov oynasi ochilmadi", "free_case_cooldown": "bepul case vaqti kelmagan",
                "bet_too_low": "stavka juda kichik", "bet_too_high": "stavka juda katta",
                "invalid_init_data": "sessiya eskirgan"}}


def activity_now(minutes: int = 15, limit: int = 40) -> dict:
    mins = max(1, min(24 * 60, int(minutes or 15)))
    online = _online(mins)
    names = {}
    if online:
        for r in _rows("SELECT telegram_id, username, first_name FROM users WHERE telegram_id = ANY(%s)",
                       (list(online.keys()),)):
            names[r["telegram_id"]] = r
    people = [{"telegram_id": k, "username": names.get(k, {}).get("username"),
               "first_name": names.get(k, {}).get("first_name"),
               "seconds_ago": int(time.time() - v[0]), "screen": SCREEN_NAMES.get(v[1] or "", v[1])}
              for k, v in sorted(online.items(), key=lambda kv: -kv[1][0])][:100]
    actions = _rows("""
        SELECT b.created_at AS at, u.username, u.first_name, b.telegram_id, b.reason AS action, b.delta AS stars_change
          FROM balance_log b JOIN users u USING (telegram_id)
         WHERE b.created_at > NOW() - make_interval(mins => %s)
         ORDER BY b.id DESC LIMIT %s
    """, (mins, _limit(limit, 40, 100)))
    return {"period_minutes": mins, "in_app_now": people, "recent_actions": actions,
            "note": "in_app_now — server oxirgi marta ishga tushgandan beri kuzatiladi"}


def support_questions(days: int = 7, limit: int = 30) -> dict:
    d = _days(days)
    rows = _rows("""
        SELECT m.created_at AS at, m.telegram_id, u.username, LEFT(m.content, 400) AS question
          FROM ai_messages m LEFT JOIN users u USING (telegram_id)
         WHERE m.scope='support' AND m.role='user' AND m.created_at > NOW() - make_interval(days => %s)
         ORDER BY m.id DESC LIMIT %s
    """, (d, _limit(limit, 30, 80)))
    return {"period_days": d, "questions": rows}


def pending_withdrawals() -> dict:
    return {"pending": _rows("""
        SELECT w.id, w.prize_name, i.prize_value, w.requested_at, u.username, u.telegram_id,
               (SELECT COALESCE(SUM(stars_amount),0) FROM payments p WHERE p.telegram_id=u.telegram_id)::bigint AS user_paid_total
          FROM withdraw_requests w JOIN users u USING (telegram_id) LEFT JOIN inventory i ON i.id = w.inventory_id
         WHERE w.status='pending' ORDER BY w.requested_at LIMIT 30
    """)}
