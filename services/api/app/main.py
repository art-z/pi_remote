from __future__ import annotations

import json
import logging
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Literal

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.metrics import collect_status

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DISPLAY_STATE_KEY = os.getenv("DISPLAY_STATE_KEY", "display:state")
DISPLAY_NOTIFY_CHANNEL = os.getenv("DISPLAY_NOTIFY_CHANNEL", "display:notify")
SYNC_QUEUE_KEY = os.getenv("SYNC_QUEUE_KEY", "sync:outbound")
FAN_STATE_KEY = os.getenv("FAN_STATE_KEY", "fan:state")
SYNC_AUTO = os.getenv("SYNC_AUTO", "false").lower() in ("1", "true", "yes")
SYNC_INTERVAL_SEC = float(os.getenv("SYNC_INTERVAL_SEC", "60"))

r: redis.Redis | None = None
_auto_sync_task: asyncio.Task | None = None


def _load_display_state() -> dict[str, Any]:
    base = _default_display_state()
    if not r:
        return base
    raw = r.get(DISPLAY_STATE_KEY)
    if not raw:
        return base
    try:
        cur = json.loads(raw)
        if not isinstance(cur, dict):
            return base
        return {**base, **cur}
    except json.JSONDecodeError:
        return base


@asynccontextmanager
async def lifespan(app: FastAPI):
    global r, _auto_sync_task
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        r.ping()
    except redis.RedisError as e:
        log.warning("Redis недоступен при старте: %s", e)

    async def auto_sync_loop():
        await asyncio.sleep(3)
        while True:
            try:
                if r:
                    r.lpush(
                        SYNC_QUEUE_KEY,
                        json.dumps(_auto_sync_payload(), ensure_ascii=False),
                    )
            except Exception as e:
                log.warning("auto sync: %s", e)
            await asyncio.sleep(SYNC_INTERVAL_SEC)

    if SYNC_AUTO:
        _auto_sync_task = asyncio.create_task(auto_sync_loop())

    yield

    if _auto_sync_task:
        _auto_sync_task.cancel()
        try:
            await _auto_sync_task
        except asyncio.CancelledError:
            pass
    if r:
        r.close()


app = FastAPI(title="pi_remote", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DisplayPayload(BaseModel):
    """Поля опциональны: в запросе передавайте только то, что меняете (merge с предыдущим состоянием)."""

    text: str | None = None
    mode: Literal["status", "pulse"] | None = None
    state: Literal["idle", "listening", "responding"] | None = None
    # luma ST7789: 0=0°, 1=90°, 2=180°, 3=270°
    rotate: int | None = Field(default=None, ge=0, le=3)
    font_size: int | None = Field(default=None, ge=8, le=48)


def _default_display_state() -> dict[str, Any]:
    return {
        "text": "",
        "mode": "status",
        "state": "idle",
        "volume_hint": 0,
        "rotate": int(os.getenv("DISPLAY_ROTATE", "2")),
        "font_size": int(os.getenv("DISPLAY_FONT_SIZE", "17")),
    }


@app.get("/api/health")
def health():
    ok = False
    try:
        if r:
            r.ping()
            ok = True
    except redis.RedisError:
        pass
    return {"ok": ok, "redis": ok}


@app.get("/api/status")
def status():
    data = collect_status()
    if r:
        try:
            raw = r.get(FAN_STATE_KEY)
            if raw:
                data["fan"] = json.loads(raw)
        except (json.JSONDecodeError, redis.RedisError):
            pass
    return data


@app.get("/api/display")
def get_display():
    if not r:
        raise HTTPException(503, "Redis недоступен")
    return _load_display_state()


@app.post("/api/display")
def set_display(body: DisplayPayload):
    if not r:
        raise HTTPException(503, "Redis недоступен")
    prev = _load_display_state()
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    data = {**prev, **patch}
    r.set(DISPLAY_STATE_KEY, json.dumps(data, ensure_ascii=False))
    try:
        r.publish(DISPLAY_NOTIFY_CHANNEL, "1")
    except redis.RedisError as e:
        log.warning("publish: %s", e)
    return {"ok": True, "display": data}


@app.post("/api/sync/enqueue")
def sync_enqueue(event: dict[str, Any]):
    """Положить произвольное событие в очередь для sync-worker."""
    if not r:
        raise HTTPException(503, "Redis недоступен")
    payload = {"type": "manual", **event}
    n = r.lpush(SYNC_QUEUE_KEY, json.dumps(payload, ensure_ascii=False))
    return {"ok": True, "queue_len": n}


def _auto_sync_payload() -> dict[str, Any]:
    s = collect_status()
    return {"type": "telemetry", "metrics": s}
