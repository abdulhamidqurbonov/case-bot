"""Jonli Crash: hamma o'yinchilar uchun bitta umumiy raund sikli.

Sikl:  STAVKA (15 s) → UCHISH (crash nuqtasigacha) → UCHIB KETDI (3 s) → yangi raund.
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

BET_SECS = 15.0         # stavka qabul qilish vaqti
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
_db_dirty = True        # stavkalar ro'yxatini bazadan qayta o'qish kerakmi
_cur: dict | None = None  # joriy raund (xotirada) — crash xabari bazani kutmasdan ketadi
_hist: list[float] | None = None


def _get_cond() -> asyncio.Condition:
    global _cond
    if _cond is None:
        _cond = asyncio.Condition()
    return _cond


async def bump(bets: bool = True) -> None:
    """Holat o'zgardi — kutib turgan barcha mijozlarga darhol javob ketadi.
    bets=False — faqat raund holati o'zgardi (bazaga murojaat qilmasdan javob beriladi)."""
    global _version, _db_dirty
    _version += 1
    if bets:
        _db_dirty = True
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
    global _snap, _db_dirty
    async with _snap_lock:
        if _snap is None or _db_dirty or (time.monotonic() - _snap["_at"]) > 2.0:
            _db_dirty = False
            s = await asyncio.to_thread(dbm.live_snapshot)
            s["_at"] = s["_now_mono"] = time.monotonic()
            _snap = s
        snap = dict(_snap)
    # Baza vaqtini hozirgi lahzaga suramiz
    snap["now"] = snap["now"] + (time.monotonic() - snap.pop("_now_mono"))
    snap.pop("_at", None)
    # Raund holati xotiradan (eng yangi) — bazaga yozilishini kutmaymiz
    cur = _cur
    if cur is not None:
        r = snap.get("round")
        if r is None or r["id"] <= cur["id"]:
            same = r is not None and r["id"] == cur["id"]
            snap["round"] = {"id": cur["id"], "status": cur["status"], "takeoff": cur["takeoff"],
                             "crashedAt": cur.get("crashedAt")}
            if cur["status"] in ("crashed", "void"):
                snap["round"]["crash"] = cur["crash"]
            if not same:
                snap["bets"], snap["players"] = [], 0
        if _hist is not None:
            snap["hist"] = _hist[:20]
    return snap


# ── Sikl ──────────────────────────────────────────────────────────────

async def _sleep_until(target_epoch: float, db_now: float, anchor: float) -> None:
    """db_now — baza vaqti `anchor` (monotonic) lahzasida. target_epoch gacha uxlaydi."""
    delay = (target_epoch - db_now) - (time.monotonic() - anchor)
    if delay > 0:
        await asyncio.sleep(delay)


async def _one_round(k: float, crash_point) -> None:
    global _cur
    crash = round(float(crash_point()), 2)
    r = await asyncio.to_thread(dbm.live_new_round, crash, BET_SECS)
    anchor = time.monotonic()
    _cur = {"id": r["id"], "status": "betting", "takeoff": r["takeoff"], "crash": crash}
    await bump()
    await _sleep_until(r["takeoff"], r["now"], anchor)

    _cur = {**_cur, "status": "flying"}
    await bump(bets=False)                                   # ekranlar darhol «uchish»ga o'tadi

    async def autos_job():
        # Bazaga yozish fonda — crash vaqtini hech qachon kechiktirmaydi (baza sekin bo'lsa ham)
        autos = await asyncio.to_thread(dbm.live_takeoff, r["id"])
        for a in autos:                                      # avto-yechishlar o'z vaqtida
            if a > crash:
                break
            await _sleep_until(r["takeoff"] + math.log(a) / k, r["now"], anchor)
            if await asyncio.to_thread(dbm.live_settle_auto, r["id"], a, crash):
                await bump()

    job = asyncio.create_task(autos_job())
    await _sleep_until(r["takeoff"] + math.log(crash) / k, r["now"], anchor)

    # Avval HAMMAGA darhol xabar (bazani kutmasdan), keyin hisob-kitob
    _cur = {**_cur, "status": "crashed", "crashedAt": r["now"] + (time.monotonic() - anchor)}
    if _hist is not None:
        _hist.insert(0, crash)
        del _hist[40:]
    await bump(bets=False)
    try:
        await asyncio.wait_for(job, 30)                     # avto-yechishlar yakunlansin
    except Exception:
        logger.exception("Avto-yechish vazifasida xato (live_crash qolganlarini hisoblaydi)")
    await asyncio.to_thread(dbm.live_crash, r["id"], crash)
    await bump()
    await asyncio.sleep(AFTER_SECS)


async def _loop(k: float, crash_point) -> None:
    global _hist
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
            _hist = (await asyncio.to_thread(dbm.live_snapshot))["hist"]
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
