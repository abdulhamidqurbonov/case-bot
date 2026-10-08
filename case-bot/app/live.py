"""Jonli Crash: hamma o'yinchilar uchun bitta umumiy raund sikli.

Sikl:  STAVKA (7 s) → UCHISH (crash nuqtasigacha) → UCHIB KETDI (3 s) → yangi raund.
* Crash nuqtasi raund boshida yaratiladi va bazada yashirin turadi.
* Vaqt hisobi baza soati bo'yicha (server soatlari farqi ta'sir qilmaydi).
* Hech kim tomosha qilmasa, sikl to'xtab turadi (bazani ortiqcha yuklamaslik uchun).
* Bir nechta server nusxasi bo'lsa, siklni faqat bittasi yuritadi (PostgreSQL advisory lock).
* Server qayta ishga tushsa, tugallanmagan raund stavkalari egalariga qaytariladi.
"""
import asyncio
import logging
import math
import time

import psycopg2

from app import database as dbm
from app.config import DATABASE_URL

logger = logging.getLogger("live")

BET_SECS = 7.0          # stavka qabul qilish vaqti
AFTER_SECS = 3.0        # «uchib ketdi»dan keyin keyingi raundgacha
IDLE_AFTER = 45.0       # shuncha soniya hech kim ko'rmasa — sikl pauza
LOCK_KEY = 774_201_001  # advisory lock raqami

_version = 0
_cond: asyncio.Condition | None = None
_snap: dict | None = None
_snap_ver = -1
_snap_lock = asyncio.Lock()
_viewers: dict[int, float] = {}
_last_view = 0.0
_task: asyncio.Task | None = None


def _get_cond() -> asyncio.Condition:
    global _cond
    if _cond is None:
        _cond = asyncio.Condition()
    return _cond


async def bump() -> None:
    """Holat o'zgardi — kutib turgan barcha mijozlarga darhol javob ketadi."""
    global _version
    _version += 1
    c = _get_cond()
    async with c:
        c.notify_all()


def mark_viewer(uid: int) -> int:
    global _last_view
    now = time.monotonic()
    _viewers[uid] = now
    _last_view = now
    for k in [k for k, t in _viewers.items() if now - t > 12]:
        _viewers.pop(k, None)
    return len(_viewers)


async def snapshot(wait_for: int | None, timeout: float = 15.0) -> tuple[dict, int]:
    """wait_for == joriy versiya bo'lsa — o'zgarish bo'lguncha (yoki timeout) kutadi (long-poll)."""
    if wait_for is not None and wait_for == _version:
        c = _get_cond()
        try:
            async with c:
                await asyncio.wait_for(c.wait_for(lambda: _version != wait_for), timeout)
        except asyncio.TimeoutError:
            pass
    return await _fresh_snapshot(), _version


async def _fresh_snapshot() -> dict:
    global _snap, _snap_ver
    async with _snap_lock:
        if _snap is None or _snap_ver != _version or (time.monotonic() - _snap["_at"]) > 2.0:
            ver = _version
            s = await asyncio.to_thread(dbm.live_snapshot)
            s["_at"] = time.monotonic()
            s["_now_mono"] = time.monotonic()
            _snap, _snap_ver = s, ver
        snap = dict(_snap)
    # Baza vaqtini hozirgi lahzaga suramiz (kesh eskirgan bo'lsa ham to'g'ri soat)
    snap["now"] = snap["now"] + (time.monotonic() - snap.pop("_now_mono"))
    snap.pop("_at", None)
    return snap


# ── Sikl ──────────────────────────────────────────────────────────────

async def _sleep_until(target_epoch: float, db_now: float, anchor: float) -> None:
    """db_now — baza vaqti `anchor` (monotonic) lahzasida. target_epoch gacha uxlaydi."""
    delay = (target_epoch - db_now) - (time.monotonic() - anchor)
    if delay > 0:
        await asyncio.sleep(delay)


async def _one_round(k: float, crash_point) -> None:
    crash = crash_point()
    r = await asyncio.to_thread(dbm.live_new_round, crash, BET_SECS)
    anchor = time.monotonic()
    await bump()
    await _sleep_until(r["takeoff"], r["now"], anchor)

    autos = await asyncio.to_thread(dbm.live_takeoff, r["id"])
    await bump()
    # Avto-yechishlar: har biri o'z vaqtida
    for a in autos:
        if a > crash:
            break
        await _sleep_until(r["takeoff"] + math.log(a) / k, r["now"], anchor)
        if await asyncio.to_thread(dbm.live_settle_auto, r["id"], a, crash):
            await bump()
    await _sleep_until(r["takeoff"] + math.log(crash) / k, r["now"], anchor)
    await asyncio.to_thread(dbm.live_crash, r["id"], crash)
    await bump()
    await asyncio.sleep(AFTER_SECS)


async def _loop(k: float, crash_point) -> None:
    lock_conn = None
    while True:
        try:
            if lock_conn is None or lock_conn.closed:
                lock_conn = await asyncio.to_thread(psycopg2.connect, DATABASE_URL, connect_timeout=15)
                lock_conn.autocommit = True
            got = await asyncio.to_thread(_try_lock, lock_conn)
            if not got:
                await asyncio.sleep(10)          # siklni boshqa server nusxasi yuritmoqda
                continue
            n = await asyncio.to_thread(dbm.live_recover)
            if n:
                logger.warning("Tugallanmagan raund: %d ta stavka qaytarildi", n)
            await bump()
            logger.info("✈️ Jonli Crash sikli ishga tushdi")
            while True:
                if time.monotonic() - _last_view > IDLE_AFTER:
                    await asyncio.sleep(0.5)
                    continue
                await _one_round(k, crash_point)
        except asyncio.CancelledError:
            if lock_conn is not None:
                lock_conn.close()
            raise
        except Exception:
            logger.exception("Jonli Crash siklida xato — 3 soniyadan keyin qayta")
            try:
                if lock_conn is not None:
                    lock_conn.close()
            except Exception:
                pass
            lock_conn = None
            await asyncio.sleep(3)


def _try_lock(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        return bool(cur.fetchone()[0])


def start(k: float, crash_point) -> None:
    global _task
    _get_cond()
    _task = asyncio.get_running_loop().create_task(_loop(k, crash_point))


async def stop() -> None:
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
