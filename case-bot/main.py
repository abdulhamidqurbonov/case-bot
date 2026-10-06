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
from app import prizes
from app.api import router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = missing_required()
    if missing:
        raise RuntimeError("Environment o'zgaruvchilari yo'q: " + ", ".join(missing))
    if not WEBAPP_URL.startswith("https://"):
        raise RuntimeError("WEBAPP_URL https:// bilan boshlanishi kerak")

    prizes.validate()
    for s in prizes.case_stats():
        if s["rtp_percent"] is not None:
            logger.info("Case %-7s narx=%5d  o'rtacha qiymat=%7.1f  sotishda RTP=%5.1f%%",
                        s["id"], s["price"], s["avg_value"], s["rtp_percent"])

    await _retry("Baza", lambda: asyncio.to_thread(dbm.init_db))

    ptb = build_app()
    await _retry("Telegram", ptb.initialize)
    await _retry("Webhook", lambda: ptb.bot.set_webhook(
        url=WEBAPP_URL + WEBHOOK_PATH,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    ))
    await ptb.start()
    logger.info("✅ Bot ishga tushdi: @%s", ptb.bot.username)

    try:
        yield
    finally:
        await ptb.stop()
        await ptb.shutdown()
        dbm.close_pool()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


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

if os.path.isdir(IMAGES_DIR):
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    if path.startswith(("api/", "webhook", "images/")):
        return Response(status_code=404)
    return FileResponse(INDEX_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
