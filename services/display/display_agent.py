"""
Агент дисплея: читает состояние из Redis (ключ display:state), слушает display:notify.
Пины SPI/GPIO как в prev/app.py — задаются через env.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from collections.abc import Callable
from typing import Optional

import redis
from dotenv import load_dotenv

load_dotenv()

from viz import PulseVisualizer, clear_screen, draw_status, idle_tick

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("display")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DISPLAY_STATE_KEY = os.getenv("DISPLAY_STATE_KEY", "display:state")
DISPLAY_NOTIFY_CHANNEL = os.getenv("DISPLAY_NOTIFY_CHANNEL", "display:notify")
TIMEZONE_KEY = os.getenv("TIMEZONE_KEY", "system:timezone")
DEFAULT_TIMEZONE = (os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow") or "Europe/Moscow").strip()
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

# luma.core.interface.serial.spi: bus_speed_hz только из этого ряда (МГц → Гц)
_LUMA_SPI_BUS_SPEEDS_HZ = tuple(
    int(m * 1_000_000) for m in (0.5, 1, 2, 4, 8, 16, 20, 24, 28, 32, 36, 40, 44, 48, 50, 52)
)


def _spi_bus_speed_hz_from_env(raw: str) -> int | None:
    if not raw:
        return None
    hz = int(raw)
    if hz in _LUMA_SPI_BUS_SPEEDS_HZ:
        return hz
    nearest = min(_LUMA_SPI_BUS_SPEEDS_HZ, key=lambda a: abs(a - hz))
    log.warning(
        "DISPLAY_SPI_SPEED_HZ=%s не из допустимого ряда luma (0.5–52 МГц дискретно); используется %s Гц",
        hz,
        nearest,
    )
    return nearest


SPI_BUS_SPEED_HZ = _spi_bus_speed_hz_from_env(SPI_SPEED_HZ)


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
    if SPI_BUS_SPEED_HZ is not None:
        spi_kw["bus_speed_hz"] = SPI_BUS_SPEED_HZ

    try:
        serial = spi(**spi_kw)
    except Exception as e:
        en = type(e).__name__
        if en == "DeviceNotFoundError" or "SPI device not found" in str(e):
            log.error(
                "SPI недоступен: нужен /dev/spidev%s.%s на хосте (включите SPI, перезагрузка). "
                "Подробности: services/display/README.md — раздел «SPI device not found».",
                SPI_PORT,
                SPI_DEVICE,
            )
        raise

    dev_kw: dict = {
        "serial_interface": serial,
        "width": DISPLAY_WIDTH,
        "height": DISPLAY_HEIGHT,
        "rotate": rot,
    }
    if GPIO_LIGHT:
        dev_kw["gpio_LIGHT"] = int(GPIO_LIGHT)

    return st7789(**dev_kw)


def _redis_timezone(r: redis.Redis) -> str:
    raw = r.get(TIMEZONE_KEY)
    if not raw or not str(raw).strip():
        return DEFAULT_TIMEZONE
    return str(raw).strip()


def _sleep_interruptible(total: float, should_continue: Callable[[], bool]) -> bool:
    """Спит total с; возвращает False, если should_continue() стало ложью (SIGTERM и т.п.)."""
    end = time.monotonic() + total
    while time.monotonic() < end:
        if not should_continue():
            return False
        time.sleep(min(0.05, end - time.monotonic()))
    return True


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
    stop_requested = False

    def _on_stop(signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        log.info("Сигнал %s — остановка после очистки экрана", signum)

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    try:
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
                SPI_BUS_SPEED_HZ if SPI_BUS_SPEED_HZ is not None else "default",
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
        alive = lambda: not stop_requested

        while not stop_requested:
            pubsub.get_message(timeout=0.001)

            tz_name = _redis_timezone(r)

            raw = (r.get(DISPLAY_STATE_KEY) or "").strip()
            if not raw:
                try:
                    idle_tick(device, FONT_PATH, DEFAULT_FONT_SIZE, tz_name=tz_name)
                except Exception as e:
                    log.warning("idle: %s", e)
                if not _sleep_interruptible(0.6, alive):
                    break
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
                if not _sleep_interruptible(pulse_frame, alive):
                    break
            else:
                lines = _status_lines(state)
                try:
                    draw_status(device, FONT_PATH, lines, font_size=desired_font, tz_name=tz_name)
                except Exception as e:
                    log.warning("draw status: %s", e)
                if not _sleep_interruptible(status_pause, alive):
                    break
    finally:
        if device:
            try:
                clear_screen(device)
                log.info("Экран очищен")
            except Exception as e:
                log.warning("очистка дисплея: %s", e)


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
