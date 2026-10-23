"""Avtopilot: admin yo'qligida AI botni kuzatib turadi.

  * 10:00 — ertalabki reja (+ kerak bo'lsa tayyor e'lon taklifi, admin bir bosishda tasdiqlaydi)
  * har 3 soatda (09–22) — tekshiruv: faqat muhim narsa bo'lsa yozadi (Steam so'rovlari kutib qolgan,
    xatolar ko'payib ketgan, xavf ostidagi o'yinchi). AI faqat shunda chaqiriladi — Groq limiti tejaladi.
  * AI_DAILY_HOUR (21:00) — kunlik hisobot.
Qaytarish eslatmalari (engage.py) avtopilotdan qat'i nazar ishlaydi (/remind_on, /remind_off).
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app import ai, engage
from app import database as dbm
from app.config import ADMIN_CHAT_ID, AI_DAILY_HOUR

logger = logging.getLogger(__name__)
TZ = ai.TZ
MORNING_HOUR = 10
CHECK_EVERY_H = 3


def auto_on() -> bool:
    return dbm.get_setting("ai_auto", "0") == "1"


def signals() -> dict:
    with dbm.db() as cur:
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'
                                                       AND requested_at < NOW() - INTERVAL '24 hours') AS withdraw_waiting_24h,
              (SELECT COUNT(*) FROM user_events WHERE kind='error' AND code <> 'network'
                                                 AND created_at > NOW() - INTERVAL '3 hours')          AS errors_3h,
              (SELECT COUNT(*) / 8.0 FROM user_events WHERE kind='error' AND code <> 'network'
                                                 AND created_at > NOW() - INTERVAL '24 hours')         AS errors_avg_3h,
              (SELECT COUNT(DISTINCT telegram_id) FROM user_events WHERE kind='error' AND code = 'server_error'
                                                 AND created_at > NOW() - INTERVAL '3 hours')          AS server_error_users_3h,
              (SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '3 hours')               AS new_users_3h,
              (SELECT COALESCE(SUM(stars_amount),0) FROM payments WHERE created_at > NOW() - INTERVAL '3 hours') AS paid_3h
        """)
        s = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in dict(cur.fetchone()).items()}
        # Xavf ostidagi o'yinchilar: 24 soatda ko'p yutqazgan va 2+ marta to'lagan
        cur.execute("""
            SELECT g.telegram_id, u.username, (SUM(g.bet) - SUM(g.payout))::bigint AS lost_24h
              FROM games g JOIN users u USING (telegram_id)
             WHERE g.created_at > NOW() - INTERVAL '24 hours'
             GROUP BY g.telegram_id, u.username
            HAVING SUM(g.bet) - SUM(g.payout) > 3000
               AND (SELECT COUNT(*) FROM payments p WHERE p.telegram_id = g.telegram_id
                                                       AND p.created_at > NOW() - INTERVAL '24 hours') >= 2
             ORDER BY lost_24h DESC LIMIT 5
        """)
        s["at_risk_players"] = [dict(r) for r in cur.fetchall()]
    return s


def notable(s: dict) -> list[str]:
    why = []
    if s["withdraw_waiting_24h"]:
        why.append("withdraw_waiting")
    if s["errors_3h"] >= 10 and s["errors_3h"] >= 2 * max(1.0, s["errors_avg_3h"]):
        why.append("error_spike")
    if s["server_error_users_3h"] >= 3:
        why.append("server_errors")
    if s["at_risk_players"]:
        why.append("at_risk")
    return why


async def _send(bot, text: str, proposals: list[str], title: str) -> None:
    from app.ai_bot import send_admin
    await send_admin(bot, f"{title}\n\n{text}", proposals)


async def _once_per_day(key: str) -> bool:
    today = datetime.now(TZ).date().isoformat()
    if await asyncio.to_thread(dbm.get_setting, key, "") == today:
        return False
    await asyncio.to_thread(dbm.set_setting, key, today)
    return True


async def tick(bot, now: datetime | None = None) -> str | None:
    """Bitta tekshiruv. Nima qilinganini qaytaradi (test uchun)."""
    if not ADMIN_CHAT_ID or not ai.enabled():
        return None
    now = now or datetime.now(TZ)
    auto = await asyncio.to_thread(auto_on)
    daily = auto or await asyncio.to_thread(dbm.get_setting, "ai_daily", "0") == "1"

    if daily and now.hour == AI_DAILY_HOUR and await _once_per_day("ai_daily_last"):
        text, props = await ai.admin_run(ai.DAILY_PROMPT, autopilot=True)
        await _send(bot, text, props, "🗓 **Kunlik hisobot**")
        return "daily"
    if not auto:
        return None
    if now.hour == MORNING_HOUR and await _once_per_day("ai_morning_last"):
        text, props = await ai.admin_run(ai.MORNING_PROMPT, autopilot=True)
        await _send(bot, text, props, "☀️ **Bugungi reja**")
        return "morning"
    if 9 <= now.hour < 22:
        last = await asyncio.to_thread(dbm.get_setting, "ai_check_last", "0")
        if now.timestamp() - float(last or 0) < CHECK_EVERY_H * 3600 - 120:
            return None
        await asyncio.to_thread(dbm.set_setting, "ai_check_last", str(int(now.timestamp())))
        s = await asyncio.to_thread(signals)
        why = notable(s)
        sig = json.dumps({"why": why, "risk": [r["telegram_id"] for r in s["at_risk_players"]],
                          "wd": s["withdraw_waiting_24h"]}, sort_keys=True)
        if not why or sig == await asyncio.to_thread(dbm.get_setting, "ai_check_sig", ""):
            return "quiet"                           # muhim narsa yo'q yoki avval aytilgan — bezovta qilmaymiz
        await asyncio.to_thread(dbm.set_setting, "ai_check_sig", sig)
        prompt = ("Avtopilot tekshiruvi. Oxirgi 3 soat signallari (JSON): " + ai.to_json(s, 2500) +
                  f"\nSabablar: {', '.join(why)}. Kerak bo'lsa user_report/errors_report/pending_withdrawals bilan "
                  "aniqlashtir. Adminga 3–6 qatorda: nima bo'ldi, qanchalik jiddiy, nima qilish kerak. "
                  "Amal kerak bo'lsa (masalan, o'yinchiga uzr xabari) — propose_* bilan taklif qil.")
        text, props = await ai.admin_run(prompt, autopilot=True)
        await _send(bot, text, props, "🛰 **Avtopilot**")
        return "alert"
    return None


async def loop(bot) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except ai.AIError as e:
            logger.warning("Avtopilot: AI xatosi %s", e.code)
        except Exception:  # noqa: BLE001
            logger.exception("Avtopilot xatosi")
        now = datetime.now(TZ)
        nxt = (now + timedelta(minutes=15)).replace(second=0, microsecond=0)
        await asyncio.sleep(max(60, (nxt - now).total_seconds()))


def start(bot) -> list[asyncio.Task]:
    loop_ = asyncio.get_running_loop()
    tasks = [loop_.create_task(engage.loop(bot))]
    if ai.enabled():
        tasks.append(loop_.create_task(loop(bot)))
    return tasks
