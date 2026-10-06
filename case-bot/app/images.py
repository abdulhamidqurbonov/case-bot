"""Skin va case rasmlari: avval bazadan (bot orqali yuklangan), keyin public/images dan."""
import os
import re
import threading

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool

from app import database as dbm

router = APIRouter()

_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "images")
_EXT_MIME = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".svg": "image/svg+xml"}
_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_cache: dict[str, tuple[bytes, str] | None] = {}
_lock = threading.Lock()
_MAX_CACHE = 300


def forget(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def _load(key: str) -> tuple[bytes, str] | None:
    with _lock:
        if key in _cache:
            return _cache[key]
    found = dbm.get_skin_image(key)
    if not found:
        for ext, mime in _EXT_MIME.items():
            path = os.path.join(_BASE, key + ext)
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
async def get_image(key: str):
    key = key.lower()
    if not _KEY_RE.match(key):
        return Response(status_code=404)
    found = await run_in_threadpool(_load, key)
    if not found:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=60"})
    data, mime = found
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"})
