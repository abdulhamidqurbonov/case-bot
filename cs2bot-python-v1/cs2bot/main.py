import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import router
from app.bot import run_bot_thread
from app.config import PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bot ni alohida threadda ishga tushirish
    run_bot_thread()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

# API routes
app.include_router(router)

# Static fayllar (rasmlar)
app.mount("/images", StaticFiles(directory="public/images"), name="images")
app.mount("/static", StaticFiles(directory="static"),        name="static")


# index.html — barcha yo'llar uchun
@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    return FileResponse("public/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
