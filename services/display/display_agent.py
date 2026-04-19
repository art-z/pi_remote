"""
Агент дисплея: читает состояние из Redis (ключ display:state), слушает display:notify.
Пины SPI/GPIO как в prev/app.py — задаются через env.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import redis
from dotenv import load_dotenv

load_dotenv()

from viz import PulseVisualizer, draw_status, idle_tick

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("display")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DISPLAY_STATE_KEY = os.getenv("DISPLAY_STATE_KEY", "display:state")
DISPLAY_NOTIFY_CHANNEL = os.getenv("DISPLAY_NOTIFY_CHANNEL", "display:notify")
FONT_PATH = os.getenv("DISPLAY_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

SPI_PORT = int(os.getenv("DISPLAY_SPI_PORT", "0"))
SPI_DEVICE = int(os.getenv("DISPLAY_SPI_DEVICE", "0"))
GPIO_DC = int(os.getenv("DISPLAY_GPIO_DC", "27"))
GPIO_RST = int(os.getenv("DISPLAY_GPIO_RST", "22"))
# prev/display.py: rotation=180; luma: 0–3 (0°, 90°, 180°, 270°)
DISPLAY_ROTATE = int(os.getenv("DISPLAY_ROTATE", "2"))
DISPLAY_WIDTH = int(os.getenv("DISPLAY_WIDTH", "240"))
DISPLAY_HEIGHT = int(os.getenv("DISPLAY_HEIGHT", "240"))
DEFAULT_FONT_SIZE = int(os.getenv("DISPLAY_FONT_SIZE", "17"))
SPI_SPEED_HZ = os.getenv("DISPLAY_SPI_SPEED_HZ", "").strip()
# Подсветка: в luma по умолчанию gpio_LIGHT=18 (как backlight в prev/display.py). Не задавайте — будет 18.
GPIO_LIGHT = os.getenv("DISPLAY_GPIO_LIGHT", "").strip()


def _load_device(rotate: Optional[int] = None):
    from luma.core.interface.serial import spi
    from luma.lcd.device import st7789

    rot = int(DISPLAY_ROTATE if rotate is None else rotate)

    spi_kw: dict = {
        "port": SPI_PORT,
        "device": SPI_DEVICE,
        "gpio_DC": GPIO_DC,
        "gpio_RST": GPIO_RST,
    }
    if SPI_SPEED_HZ:
        spi_kw["bus_speed_hz"] = int(SPI_SPEED_HZ)

    serial = spi(**spi_kw)

    dev_kw: dict = {
        "serial_interface": serial,
        "width": DISPLAY_WIDTH,
        "height": DISPLAY_HEIGHT,
        "rotate": rot,
    }
    if GPIO_LIGHT:
        dev_kw["gpio_LIGHT"] = int(GPIO_LIGHT)

    return st7789(**dev_kw)


def _int_from_state(state: dict, key: str, default: int) -> int:
    v = state.get(key)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def main():
    device = None
    current_rotate = DISPLAY_ROTATE
    try:
        device = _load_device()
        log.info(
            "ST7789 %sx%s rotate=%s SPI %s.%s DC=%s RST=%s speed=%s light=%s",
            DISPLAY_WIDTH,
            DISPLAY_HEIGHT,
            current_rotate,
            SPI_PORT,
            SPI_DEVICE,
            GPIO_DC,
            GPIO_RST,
            SPI_SPEED_HZ or "default",
            GPIO_LIGHT or "18 (luma default)",
        )
    except Exception as e:
        log.error("Дисплей недоступен: %s", e)
        raise

    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(DISPLAY_NOTIFY_CHANNEL)

    viz = PulseVisualizer(device, FONT_PATH, DEFAULT_FONT_SIZE)
    pulse_frame = float(os.getenv("DISPLAY_PULSE_FRAME_SEC", "0.08"))
    status_pause = float(os.getenv("DISPLAY_STATUS_POLL_SEC", "0.35"))

    while True:
        pubsub.get_message(timeout=0.001)

        raw = (r.get(DISPLAY_STATE_KEY) or "").strip()
        if not raw:
            try:
                idle_tick(device, FONT_PATH, DEFAULT_FONT_SIZE)
            except Exception as e:
                log.warning("idle: %s", e)
            time.sleep(0.6)
            continue

        state = _parse_state(raw)
        desired_rotate = max(0, min(3, _int_from_state(state, "rotate", DISPLAY_ROTATE)))
        desired_font = max(8, min(48, _int_from_state(state, "font_size", DEFAULT_FONT_SIZE)))

        if desired_rotate != current_rotate:
            try:
                device = _load_device(desired_rotate)
                current_rotate = desired_rotate
                viz = PulseVisualizer(device, FONT_PATH, desired_font)
            except Exception as e:
                log.warning("смена поворота %s: %s", desired_rotate, e)
        else:
            viz.set_font_sizes(desired_font)

        if state.get("mode") == "pulse":
            viz.set_state(state.get("state") or "idle")
            viz.set_text(state.get("text") or "")
            v = state.get("volume_hint")
            if isinstance(v, (int, float)):
                viz.set_volume_hint(int(v))
            try:
                viz.update()
            except Exception as e:
                log.warning("draw pulse: %s", e)
            time.sleep(pulse_frame)
        else:
            lines = _status_lines(state)
            try:
                draw_status(device, FONT_PATH, lines, font_size=desired_font)
            except Exception as e:
                log.warning("draw status: %s", e)
            time.sleep(status_pause)


def _parse_state(raw: str) -> dict:
    if not raw.strip():
        return {"mode": "status", "text": "", "state": "idle"}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"mode": "status", "text": raw[:200], "state": "idle"}


def _status_lines(state: dict) -> list[str]:
    text = (state.get("text") or "").strip()
    if text:
        return text.split("\n")
    return [
        "pi_remote",
        "режим: status",
        "задайте текст с веб-страницы",
    ]


if __name__ == "__main__":
    main()
