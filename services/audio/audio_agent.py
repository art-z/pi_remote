"""
Микрофон (ALSA raw 16 kHz mono) → Vosk STT (русский) → Redis display:state + display:notify.
Модель по умолчанию: small-ru (см. Dockerfile); переопределение: AUDIO_MODEL_PATH на смонтированный том.
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

    log.info("Загрузка Vosk из %s …", AUDIO_MODEL_PATH)
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
