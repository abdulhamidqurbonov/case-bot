from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import router
from app.bot import run_bot_thread
from app.config import PORT

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
IMAGES_DIR = PUBLIC_DIR / "images"
STATIC_DIR = PUBLIC_DIR / "static"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bot ni alohida threadda ishga tushirish
    run_bot_thread()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

# API routes
app.include_router(router)

# Static fayllar (rasmlar)
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# index.html — barcha yo'llar uchun
@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    return FileResponse(PUBLIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
