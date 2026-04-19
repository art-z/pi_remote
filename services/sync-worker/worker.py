"""
Забирает JSON-события из Redis (LIST sync:outbound) и отправляет на внешний сервер.
Пустой REMOTE_SYNC_URL — воркер спит, очередь копится (или заполняется локально для последующей синхронизации).
"""

from __future__ import annotations

import json
import logging
import os
import time

import httpx
import redis
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sync-worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = os.getenv("SYNC_QUEUE_KEY", "sync:outbound")
# Полный URL endpoint (например https://host/api/v1/pi/ingest)
REMOTE_URL = os.getenv("REMOTE_SYNC_URL", "").strip()
REMOTE_TOKEN = os.getenv("REMOTE_SYNC_TOKEN", "").strip()
REMOTE_TIMEOUT = float(os.getenv("REMOTE_SYNC_TIMEOUT_SEC", "15"))
BRPOP_TIMEOUT = int(os.getenv("SYNC_BRPOP_TIMEOUT_SEC", "5"))


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if REMOTE_TOKEN:
        h["Authorization"] = f"Bearer {REMOTE_TOKEN}"
    return h


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    log.info("Очередь %s, remote=%s", QUEUE_KEY, REMOTE_URL or "(выкл.)")

    while True:
        if not REMOTE_URL:
            time.sleep(10)
            continue

        try:
            item = r.brpop(QUEUE_KEY, timeout=BRPOP_TIMEOUT)
        except redis.RedisError as e:
            log.warning("Redis: %s", e)
            time.sleep(2)
            continue

        if item is None:
            continue

        _, payload = item
        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("Пропуск не-JSON: %s", payload[:200])
            continue

        try:
            resp = httpx.post(REMOTE_URL, json=body, headers=_headers(), timeout=REMOTE_TIMEOUT)
            if resp.status_code >= 400:
                log.warning("Ответ %s: %s", resp.status_code, resp.text[:500])
                r.lpush(QUEUE_KEY, payload)
                time.sleep(2)
            else:
                log.debug("Отправлено ok: %s", body.get("type"))
        except httpx.HTTPError as e:
            log.warning("Сеть: %s — возвращаю в очередь", e)
            r.lpush(QUEUE_KEY, payload)
            time.sleep(2)


if __name__ == "__main__":
    main()
