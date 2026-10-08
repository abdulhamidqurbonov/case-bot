"""/img/<kalit> — rasm va ovozlar: avval bazadan (bot orqali yuklangan), keyin public/images dan."""
import os
import re
import threading

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app import database as dbm
from app.media import STATIC_DIR, STATIC_EXT

router = APIRouter()

_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_cache: dict[str, tuple[bytes, str] | None] = {}
_lock = threading.Lock()
_MAX_CACHE = 400


def forget(key: str | None = None) -> None:
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def _load(key: str) -> tuple[bytes, str] | None:
    with _lock:
        if key in _cache:
            return _cache[key]
    found = dbm.get_skin_image(key)
    if not found:
        for ext, mime in STATIC_EXT.items():
            path = os.path.join(STATIC_DIR, key + ext)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    found = (f.read(), mime)
                break
    with _lock:
        if len(_cache) >= _MAX_CACHE:
            _cache.clear()
        _cache[key] = found
    return found


@router.get("/img/{key}")
async def get_media(key: str, request: Request):
    key = key.lower()
    if not _KEY_RE.match(key):
        return Response(status_code=404)
    found = await run_in_threadpool(_load, key)
    if not found:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=60"})
    data, mime = found
    # ?v=<versiya> bilan so'ralsa — o'zgarmaydi, telefon uni uzoq saqlaydi (qayta yuklamaydi)
    cache = "public, max-age=31536000, immutable" if request.query_params.get("v") else "public, max-age=3600"
    return Response(content=data, media_type=mime, headers={"Cache-Control": cache})
