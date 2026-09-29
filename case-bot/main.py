import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from telegram import Update
from app.api import router
from app.bot import build_app, get_app
from app.database import init_db
from app.config import BOT_TOKEN, WEBAPP_URL, PORT

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{WEBAPP_URL}{WEBHOOK_PATH}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Baza jadvallarini yaratish
    init_db()

    # Bot va webhook
    ptb_app = build_app()
    await ptb_app.initialize()
    await ptb_app.bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info(f"✅ Webhook: {WEBHOOK_URL}")
    await ptb_app.start()

    yield

    await ptb_app.stop()
    await ptb_app.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data   = await request.json()
    update = Update.de_json(data, get_app().bot)
    await get_app().process_update(update)
    return Response(status_code=200)


app.include_router(router)

if os.path.exists("public/images"):
    app.mount("/images", StaticFiles(directory="public/images"), name="images")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    if any(path.startswith(p) for p in ("api/", "webhook/", "images/", "health")):
        return Response(status_code=404)
    return FileResponse("public/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)