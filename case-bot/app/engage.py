"""Qaytarish eslatmalari: botga kirmay qo'ygan o'yinchiga «bepul case tayyor» xabari.

Qoidalar (spam bo'lmasligi uchun):
  * Faqat bepul case'i tayyor va REMIND_AFTER_H soatdan beri kirmagan o'yinchiga.
  * Bitta «kirmay qolish» davrida ko'pi bilan 4 ta eslatma: darhol, +2 kun, +4 kun, +7 kun.
    O'yinchi qaytib kirsa — hisob noldan boshlanadi.
  * Faqat 10:00–21:00 (Toshkent) oralig'ida. Har xabar ostida «Eslatmalarni o'chirish» tugmasi.
  * Botni bloklagan o'yinchiga boshqa yuborilmaydi (qaytib /start bossa — yana yuboriladi).
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import BadRequest, Forbidden, RetryAfter

from app import database as dbm
from app.config import FREE_CASE_COOLDOWN_H, REMIND_AFTER_H, REMIND_ENABLED, app_url

logger = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=5))
GAPS_H = [48, 96, 168]          # 2-, 3-, 4-eslatma oldingisidan necha soat keyin
MAX_PER_STREAK = 1 + len(GAPS_H)
BATCH = 400                     # bir yurishda ko'pi bilan nechta xabar
HOURS = (10, 21)                # yuborish oynasi (Toshkent)


def enabled() -> bool:
    return dbm.get_setting("remind_enabled", "1" if REMIND_ENABLED else "0") == "1"


def set_enabled(on: bool) -> None:
    dbm.set_setting("remind_enabled", "1" if on else "0")


def candidates(limit: int = BATCH) -> list[dict]:
    with dbm.db() as cur:
        cur.execute("""
            SELECT telegram_id, first_name, reminders_sent, last_reminded_at,
                   COALESCE(last_seen_at, created_at) AS seen
              FROM users
             WHERE NOT COALESCE(bot_blocked, FALSE) AND NOT COALESCE(no_remind, FALSE)
               AND (free_case_used_at IS NULL OR free_case_used_at < NOW() - make_interval(hours => %s))
               AND COALESCE(last_seen_at, created_at) < NOW() - make_interval(hours => %s)
             ORDER BY COALESCE(last_seen_at, created_at) DESC
             LIMIT 5000
        """, (FREE_CASE_COOLDOWN_H, REMIND_AFTER_H))
        rows = [dict(r) for r in cur.fetchall()]
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        last, seen = r["last_reminded_at"], r["seen"]
        if last is None or last < seen:                 # qaytib kirgan — yangi davr
            r["streak"] = 0
        else:
            n = r["reminders_sent"] or 0
            if n >= MAX_PER_STREAK or now - last < timedelta(hours=GAPS_H[n - 1] if n >= 1 else 0):
                continue
            r["streak"] = n
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _context() -> dict:
    with dbm.db() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM inventory WHERE obtained_at > NOW() - INTERVAL '2 days'")
        wins = cur.fetchone()["n"]
        cur.execute("SELECT name, created_at FROM custom_cases WHERE active ORDER BY created_at DESC LIMIT 1")
        new = cur.fetchone()
    return {"wins": wins, "new_case": dict(new) if new else None}


def message_for(r: dict, ctx: dict) -> str:
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    name = esc((r.get("first_name") or "do'stim")[:30])
    nc = ctx.get("new_case")
    if nc and nc["created_at"] > r["seen"]:
        return (f"🆕 {name}, siz yo'qligingizda yangi case qo'shildi: <b>{esc(nc['name'])}</b>!\n\n"
                "🎁 Bepul case'ingiz ham tayyor — bir bosishda oching.")
    options = [
        f"🎁 {name}, bepul case'ingiz tayyor!\n\nBugungi omadingizni sinab ko'ring — bir bosishda ochiladi.",
        f"⏳ {name}, bepul case sizni kutyapti.\n\nHar kuni yangilanadi — bugungisini qo'ldan boy bermang 😉",
        f"👋 {name}, sizni sog'indik!\n\n🎁 Bepul case tayyor turibdi — ichida qanday skin borligini bilib oling.",
    ]
    if ctx.get("wins", 0) >= 20:
        options.append(f"🔥 {name}, oxirgi 2 kunda o'yinchilar <b>{ctx['wins']}</b> ta skin yutib olishdi.\n\n"
                       "🎁 Sizning bepul case'ingiz ham tayyor!")
    return options[r["streak"] % len(options)] if r["streak"] else random.choice(options)


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Bepul case'ni ochish", web_app=WebAppInfo(url=app_url("free")))],
        [InlineKeyboardButton("🔕 Eslatmalarni o'chirish", callback_data="rm:off")],
    ])


def _mark(uid: int, streak: int, blocked: bool = False) -> None:
    with dbm.db() as cur:
        if blocked:
            cur.execute("UPDATE users SET bot_blocked = TRUE WHERE telegram_id = %s", (uid,))
        else:
            cur.execute("UPDATE users SET last_reminded_at = NOW(), reminders_sent = %s WHERE telegram_id = %s",
                        (streak + 1, uid))


def opt_out(uid: int) -> None:
    with dbm.db() as cur:
        cur.execute("UPDATE users SET no_remind = TRUE WHERE telegram_id = %s", (uid,))


def unblock(uid: int) -> None:
    with dbm.db() as cur:
        cur.execute("UPDATE users SET bot_blocked = FALSE WHERE telegram_id = %s", (uid,))


def stats() -> dict:
    with dbm.db() as cur:
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM users WHERE last_reminded_at > NOW() - INTERVAL '1 day')  AS sent_24h,
              (SELECT COUNT(*) FROM users WHERE last_reminded_at > NOW() - INTERVAL '7 days') AS reminded_7d,
              (SELECT COUNT(*) FROM users WHERE last_reminded_at > NOW() - INTERVAL '7 days'
                                            AND last_seen_at > last_reminded_at)              AS came_back_7d,
              (SELECT COUNT(*) FROM users WHERE bot_blocked)                                  AS blocked_bot,
              (SELECT COUNT(*) FROM users WHERE no_remind)                                    AS opted_out
        """)
        st = dict(cur.fetchone())
    st["enabled"] = enabled()
    st["waiting_now"] = len(candidates(5000))
    return st


def _in_window() -> bool:
    return HOURS[0] <= datetime.now(TZ).hour < HOURS[1]


async def run_once(bot, force: bool = False) -> dict:
    """Bitta yurish: navbatdagilarga eslatma yuboradi. Natija: yuborildi/bloklagan/xato."""
    from app.admin_cases import _bcast_lock
    res = {"sent": 0, "blocked": 0, "failed": 0}
    if not force and (not _in_window() or not await asyncio.to_thread(enabled)):
        return res
    if _bcast_lock.locked():                      # e'lon ketayotgan bo'lsa — Telegram limitiga urilmaslik uchun kutamiz
        return res
    rows = await asyncio.to_thread(candidates, BATCH)
    if not rows:
        return res
    ctx = await asyncio.to_thread(_context)
    for r in rows:
        uid = r["telegram_id"]
        for attempt in range(3):
            try:
                await bot.send_message(uid, message_for(r, ctx), parse_mode="HTML", reply_markup=keyboard())
                await asyncio.to_thread(_mark, uid, r["streak"])
                res["sent"] += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(float(getattr(e, "retry_after", 3)) + 0.5)
            except Forbidden:
                await asyncio.to_thread(_mark, uid, 0, True)
                res["blocked"] += 1
                break
            except BadRequest:
                await asyncio.to_thread(_mark, uid, 0, True)   # chat topilmadi — keyin urinmaymiz
                res["failed"] += 1
                break
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    res["failed"] += 1
                await asyncio.sleep(1)
        await asyncio.sleep(0.06)                 # ~16 xabar/soniya
    logger.info("Eslatmalar: %s", res)
    return res


async def loop(bot) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Eslatma yuborishda xato")
        await asyncio.sleep(1800)                 # har 30 daqiqada tekshiradi
