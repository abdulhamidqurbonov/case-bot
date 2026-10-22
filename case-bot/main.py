"""Kirish nuqtasi: FastAPI server + Telegram webhook."""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.error import NetworkError, TimedOut

from app import database as dbm
from app import catalog, games, live
from app.api import router
from app.images import router as images_router
from app.bot import build_app, get_app
from app.config import PORT, WEBAPP_URL, WEBHOOK_SECRET, missing_required

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # so'rov URL'larida token bor
logger = logging.getLogger("main")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR  = os.path.join(BASE_DIR, "public")
IMAGES_DIR  = os.path.join(PUBLIC_DIR, "images")
INDEX_HTML  = os.path.join(PUBLIC_DIR, "index.html")
WEBHOOK_PATH = "/webhook"


async def _retry(name: str, func, attempts: int = 5):
    """Vaqtinchalik tarmoq xatolarida qayta urinadi."""
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except Exception as e:
            transient = isinstance(e, (TimedOut, NetworkError, dbm.psycopg2.OperationalError))
            if not transient or attempt == attempts:
                raise
            wait = 3 * attempt
            logger.warning("%s: urinish %d/%d muvaffaqiyatsiz (%s). %ds kutamiz...",
                           name, attempt, attempts, e.__class__.__name__, wait)
            await asyncio.sleep(wait)


async def _keep_alive() -> None:
    """Render'ning bepul serveri uxlab qolmasligi uchun o'zining tashqi manziliga so'rov yuboradi.
    So'rov Render proksisi orqali o'tadi, shuning uchun «kiruvchi trafik» hisoblanadi."""
    import httpx
    url = WEBAPP_URL + "/health"
    await asyncio.sleep(60)
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            try:
                r = await client.get(url, headers={"User-Agent": "CaseVault-keepalive"})
                if r.status_code != 200:
                    logger.warning("Keep-alive: %s javob berdi %s", url, r.status_code)
            except Exception as e:  # noqa: BLE001
                logger.warning("Keep-alive xatosi: %s", e.__class__.__name__)
            await asyncio.sleep(600)                       # 10 daqiqa (Render 15 daqiqada uxlatadi)


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = missing_required()
    if missing:
        raise RuntimeError("Environment o'zgaruvchilari yo'q: " + ", ".join(missing))
    if not WEBAPP_URL.startswith("https://"):
        raise RuntimeError("WEBAPP_URL https:// bilan boshlanishi kerak")

    catalog.validate()
    for c in catalog.CASE_LIST:
        logger.info("Case %-8s narx=%6d ⭐  o'rtacha yutuq=%8.1f  RTP=%s",
                    c["id"], c["price"], c["avg_value"], f"{c['rtp']}%" if c["rtp"] else "bepul")

    await _retry("Baza", lambda: asyncio.to_thread(dbm.init_db))
    from app import store
    await asyncio.to_thread(store.reload)              # bot orqali qo'shilgan case'lar

    ptb = build_app()
    await _retry("Telegram", ptb.initialize)
    await _retry("Webhook", lambda: ptb.bot.set_webhook(
        url=WEBAPP_URL + WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    ))
    await ptb.start()
    from app.config import FRONTEND_URL, app_url
    if FRONTEND_URL:
        # Pastki chapdagi menyu tugmasi ham uxlamaydigan sahifani ochsin
        from telegram import MenuButtonWebApp, WebAppInfo
        try:
            await ptb.bot.set_chat_menu_button(menu_button=MenuButtonWebApp("🎮 O'ynash", WebAppInfo(app_url())))
        except Exception as e:  # noqa: BLE001
            logger.warning("Menyu tugmasini o'rnatib bo'lmadi: %s", e)
    live.start(games.CRASH_K, lambda: games.crash_point())
    from app.config import KEEP_ALIVE
    ka = asyncio.get_running_loop().create_task(_keep_alive()) if KEEP_ALIVE else None
    from app import ai
    daily = asyncio.get_running_loop().create_task(ai.daily_loop()) if ai.enabled() else None
    logger.info("AI: %s", "yoqilgan" if ai.enabled() else "o'chiq (GROQ_API_KEY yo'q)")
    logger.info("✅ Bot ishga tushdi: @%s", ptb.bot.username)
    from app.config import ADMIN_CHAT_ID
    logger.info("Admin ID: %s", ADMIN_CHAT_ID or "SOZLANMAGAN (rasm yuklash ishlamaydi)")

    try:
        yield
    finally:
        if ka:
            ka.cancel()
        if daily:
            daily.cancel()
        await ai.close()
        await live.stop()
        await ptb.stop()
        await ptb.shutdown()
        dbm.close_pool()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Ilova sahifasi boshqa hostingda (FRONTEND_URL) bo'lsa — faqat o'sha saytga API'dan foydalanishga ruxsat
from app.config import FRONTEND_URL  # noqa: E402
if FRONTEND_URL:
    from urllib.parse import urlsplit
    from fastapi.middleware.cors import CORSMiddleware
    _u = urlsplit(FRONTEND_URL)
    app.add_middleware(CORSMiddleware, allow_origins=[f"{_u.scheme}://{_u.netloc}"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"], max_age=86400)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return Response(status_code=403)
    try:
        ptb = get_app()
        update = Update.de_json(await request.json(), ptb.bot)
        await ptb.process_update(update)
    except Exception:
        logger.exception("Webhook update'ni qayta ishlashda xato")
    return Response(status_code=200)


app.include_router(router)
app.include_router(images_router)

if os.path.isdir(IMAGES_DIR):
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    if path.startswith(("api/", "webhook", "images/", "img/")):
        return Response(status_code=404)
    return FileResponse(INDEX_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
