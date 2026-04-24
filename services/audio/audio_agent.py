"""
Микрофон (ALSA raw 16 kHz mono) → Vosk STT (русский) → Redis display:state + display:notify.
Модель: каталог на хосте монтируется в AUDIO_MODEL_PATH (по умолчанию /opt/vosk-model); см. models/README.md.
"""

from __future__ import annotations

import array
import json
import logging
import math
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import redis
from dotenv import load_dotenv
from vosk import KaldiRecognizer, Model

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("audio")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DISPLAY_STATE_KEY = os.getenv("DISPLAY_STATE_KEY", "display:state")
DISPLAY_NOTIFY_CHANNEL = os.getenv("DISPLAY_NOTIFY_CHANNEL", "display:notify")
AUDIO_MODEL_PATH = os.getenv("AUDIO_MODEL_PATH", "/opt/vosk-model").strip()
AUDIO_ALSA_DEVICE = (os.getenv("AUDIO_ALSA_DEVICE", "default") or "default").strip()
SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
CHUNK_BYTES = max(2000, int(os.getenv("AUDIO_CHUNK_BYTES", "8000")))
PARTIAL_PUBLISH_SEC = float(os.getenv("AUDIO_PARTIAL_PUBLISH_SEC", "0.25"))
DISPLAY_MODE = (os.getenv("AUDIO_DISPLAY_MODE", "pulse") or "pulse").strip().lower()
if DISPLAY_MODE not in ("pulse", "status"):
    DISPLAY_MODE = "pulse"

SYNC_QUEUE_KEY = os.getenv("SYNC_QUEUE_KEY", "sync:outbound")
AUDIO_HISTORY_KEY = os.getenv("AUDIO_HISTORY_KEY", "audio:history")
AUDIO_HISTORY_MAX = int(os.getenv("AUDIO_HISTORY_MAX", "500"))
AUDIO_STORE_HISTORY = os.getenv("AUDIO_STORE_HISTORY", "true").lower() in ("1", "true", "yes")
AUDIO_PUSH_TO_SYNC_QUEUE = os.getenv("AUDIO_PUSH_TO_SYNC_QUEUE", "true").lower() in ("1", "true", "yes")
REMOTE_SYNC_URL = os.getenv("REMOTE_SYNC_URL", "").strip()


def _default_display_state() -> dict[str, Any]:
    return {
        "text": "",
        "mode": "status",
        "state": "idle",
        "volume_hint": 0,
        "rotate": int(os.getenv("DISPLAY_ROTATE", "2")),
        "font_size": int(os.getenv("DISPLAY_FONT_SIZE", "17")),
    }


def _merge_display(r: redis.Redis, patch: dict[str, Any]) -> None:
    raw = (r.get(DISPLAY_STATE_KEY) or "").strip()
    if raw:
        try:
            prev = json.loads(raw)
            if not isinstance(prev, dict):
                prev = _default_display_state()
        except json.JSONDecodeError:
            prev = _default_display_state()
    else:
        prev = _default_display_state()
    base = _default_display_state()
    data = {**base, **prev, **patch}
    r.set(DISPLAY_STATE_KEY, json.dumps(data, ensure_ascii=False))
    try:
        r.publish(DISPLAY_NOTIFY_CHANNEL, "1")
    except redis.RedisError as e:
        log.warning("publish display:notify: %s", e)


def _rms_volume_hint(chunk: bytes) -> int:
    if len(chunk) < 2:
        return 0
    n = len(chunk) - (len(chunk) % 2)
    a = array.array("h")
    a.frombytes(chunk[:n])
    if not a:
        return 0
    acc = sum(x * x for x in a)
    rms = math.sqrt(acc / len(a))
    # Грубая шкала 0–100 для визуализатора на дисплее
    return min(100, int(rms / 80.0))


def _persist_final_transcript(r: redis.Redis, text: str) -> None:
    """Redis LIST последних распознаваний + постановка в sync:outbound для sync-worker → REMOTE_SYNC_URL."""
    recognized_at = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "text": text,
        "recognized_at": recognized_at,
        "lang": "ru",
        "source": "pi_remote_audio",
    }

    if AUDIO_STORE_HISTORY and AUDIO_HISTORY_MAX > 0:
        try:
            r.lpush(AUDIO_HISTORY_KEY, json.dumps(record, ensure_ascii=False))
            r.ltrim(AUDIO_HISTORY_KEY, 0, max(0, AUDIO_HISTORY_MAX - 1))
        except redis.RedisError as e:
            log.warning("audio history: %s", e)

    if not AUDIO_PUSH_TO_SYNC_QUEUE or not REMOTE_SYNC_URL:
        return

    outbound = {"type": "stt", **record}
    try:
        r.lpush(SYNC_QUEUE_KEY, json.dumps(outbound, ensure_ascii=False))
    except redis.RedisError as e:
        log.warning("sync queue: %s", e)


def _arecord_cmd() -> list[str]:
    return [
        "arecord",
        "-D",
        AUDIO_ALSA_DEVICE,
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        str(SAMPLE_RATE),
        "-t",
        "raw",
        "-q",
    ]


def main() -> None:
    if not os.path.isdir(AUDIO_MODEL_PATH):
        log.error("Нет каталога модели Vosk: %s (задайте AUDIO_MODEL_PATH)", AUDIO_MODEL_PATH)
        raise SystemExit(1)

    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()

    log.info(
        "Загрузка Vosk из %s … (история %s, очередь sync=%s, remote=%s)",
        AUDIO_MODEL_PATH,
        "on" if AUDIO_STORE_HISTORY and AUDIO_HISTORY_MAX > 0 else "off",
        "on" if AUDIO_PUSH_TO_SYNC_QUEUE and REMOTE_SYNC_URL else "off",
        "set" if REMOTE_SYNC_URL else "empty",
    )
    model = Model(AUDIO_MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(False)

    stop = False

    def _sig(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    last_partial_publish = 0.0
    last_partial_text = ""

    while not stop:
        proc: subprocess.Popen[bytes] | None = None
        try:
            log.info("Запись ALSA: %s @ %s Гц", AUDIO_ALSA_DEVICE, SAMPLE_RATE)
            proc = subprocess.Popen(
                _arecord_cmd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdout is not None

            while not stop:
                chunk = proc.stdout.read(CHUNK_BYTES)
                if not chunk:
                    err = ""
                    if proc.stderr:
                        try:
                            err = proc.stderr.read().decode("utf-8", errors="replace").strip()
                        except Exception:
                            err = ""
                    log.warning("arecord завершился (код %s)%s", proc.wait(), f": {err}" if err else "")
                    if err and ("No such file" in err or "audio open error" in err):
                        log.error(
                            "ALSA не открылась (%s). Проверьте: ls -l /dev/snd на хосте и в контейнере; "
                            "arecord -l; задайте AUDIO_ALSA_DEVICE=plughw:C,D. См. services/audio/README.md — "
                            "раздел «audio open error: No such file or directory».",
                            AUDIO_ALSA_DEVICE,
                        )
                    break

                vol = _rms_volume_hint(chunk)

                if rec.AcceptWaveform(chunk):
                    try:
                        res = json.loads(rec.Result())
                    except json.JSONDecodeError:
                        res = {}
                    text = (res.get("text") or "").strip()
                    if text:
                        log.info("final: %s", text)
                        _persist_final_transcript(r, text)
                        _merge_display(
                            r,
                            {
                                "mode": DISPLAY_MODE,
                                "state": "responding",
                                "text": text,
                                "volume_hint": vol,
                            },
                        )
                        last_partial_text = ""
                else:
                    try:
                        partial = json.loads(rec.PartialResult())
                    except json.JSONDecodeError:
                        partial = {}
                    ptext = (partial.get("partial") or "").strip()
                    now = time.monotonic()
                    if ptext and (ptext != last_partial_text or now - last_partial_publish >= PARTIAL_PUBLISH_SEC):
                        last_partial_text = ptext
                        last_partial_publish = now
                        _merge_display(
                            r,
                            {
                                "mode": DISPLAY_MODE,
                                "state": "listening",
                                "text": ptext,
                                "volume_hint": vol,
                            },
                        )
                    elif not ptext and last_partial_text:
                        last_partial_text = ""
                        _merge_display(
                            r,
                            {
                                "mode": DISPLAY_MODE,
                                "state": "idle",
                                "volume_hint": vol,
                            },
                        )

        except FileNotFoundError:
            log.error("Команда arecord не найдена (установите alsa-utils)")
            raise SystemExit(1)
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if not stop:
            time.sleep(0.5)

    log.info("Остановка")


if __name__ == "__main__":
    main()
