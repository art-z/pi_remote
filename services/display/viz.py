"""Упрощённая отрисовка ST7789: режим pulse (как в prev/visualizer) и status (текст).
Размеры как в prev/display.py — через DISPLAY_WIDTH / DISPLAY_HEIGHT (по умолчанию 240)."""

from __future__ import annotations

import colorsys
import os
import textwrap
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH = int(os.getenv("DISPLAY_WIDTH", "240"))
HEIGHT = int(os.getenv("DISPLAY_HEIGHT", "240"))
CENTER = (WIDTH // 2, HEIGHT // 2)

DEFAULT_FONT_SIZE = int(os.getenv("DISPLAY_FONT_SIZE", "17"))
DEFAULT_TIMEZONE = (os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow") or "Europe/Moscow").strip()


def _now_for_clock(tz_name: Optional[str] = None) -> datetime:
    """Текущее время для часов; при ошибке пояса — дефолт из env."""
    name = (tz_name or "").strip() or DEFAULT_TIMEZONE
    try:
        return datetime.now(ZoneInfo(name))
    except Exception:
        try:
            return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
        except Exception:
            return datetime.now()


def _wrap_cols(body_px: int, font_px: int, ref_cols: int = 28, ref_px: int = 17) -> int:
    """Грубая оценка числа колонок для textwrap при изменении кегля."""
    return max(8, int(ref_cols * (ref_px / max(font_px, 1))))


class PulseVisualizer:
    def __init__(self, device, font_path: str, font_size: Optional[int] = None):
        self.text = ""
        self.color = "white"
        self.device = device
        self._font_path = font_path
        self.volume_level = 0
        self.phase = 0.0
        self.state = "idle"
        self._font_size_main = 0
        self._font_size_small = 0
        self.font = None  # type: ignore
        self.font_small = None  # type: ignore
        self.set_font_sizes(font_size)

    def set_font_sizes(self, font_size: Optional[int]):
        """Основной кегль и чуть меньший для подписей; при том же значении — без перезагрузки шрифтов."""
        main = int(font_size) if font_size is not None else DEFAULT_FONT_SIZE
        main = max(8, min(48, main))
        small = max(10, main - 2)
        if main == self._font_size_main and small == self._font_size_small:
            return
        self._font_size_main = main
        self._font_size_small = small
        self.font = ImageFont.truetype(self._font_path, main)
        self.font_small = ImageFont.truetype(self._font_path, small)

    def set_state(self, state: str):
        self.state = state

    def set_text(self, text: str):
        self.text = text

    def set_volume_hint(self, value: int):
        self.volume_level = max(0, min(100, int(value)))

    def volume_color(self):
        hue = (self.volume_level / 100) * 0.33
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        return (int(r * 255), int(g * 255), int(b * 255))

    def update(self):
        image = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(image)

        if self.state == "idle":
            base_radius = 15
            ring_radius = base_radius
            color = (30, 30, 30)
        elif self.state == "responding":
            base_radius = 30
            ring_radius = base_radius
            color = (255, 255, 255)
        else:
            base_radius = 20 + (self.volume_level / 1.5)
            ring_radius = base_radius + (self.volume_level / 4) * np.sin(self.phase)
            color = self.volume_color()
            self.phase += 0.15

        bbox_outer = [
            CENTER[0] - ring_radius,
            CENTER[1] - ring_radius,
            CENTER[0] + ring_radius,
            CENTER[1] + ring_radius,
        ]
        bbox_inner = [
            CENTER[0] - ring_radius + 6,
            CENTER[1] - ring_radius + 6,
            CENTER[0] + ring_radius - 6,
            CENTER[1] + ring_radius - 6,
        ]

        draw.ellipse(bbox_outer, fill=color)
        draw.ellipse(bbox_inner, fill="black")

        wrap_w = _wrap_cols(WIDTH - 20, self._font_size_small, ref_cols=26, ref_px=16)
        display_text = self.text
        lines: list[str] = []
        for paragraph in display_text.split("\n"):
            for line in textwrap.wrap(paragraph, width=wrap_w) if paragraph else [""]:
                if line:
                    lines.append(line)
        if len(lines) > 6:
            lines = lines[:6]

        line_h = max(12, self._font_size_small + 4)
        y = HEIGHT - 10 - line_h * len(lines) if lines else HEIGHT - 30
        for line in lines:
            draw.text((10, y), line, fill=self.color, font=self.font_small)
            bbox = draw.textbbox((10, y), line, font=self.font_small)
            y = bbox[3] + 2

        if self.device:
            self.device.display(image)


def draw_status(
    device,
    font_path: str,
    lines: list[str],
    font_size: Optional[int] = None,
    tz_name: Optional[str] = None,
):
    body = int(font_size) if font_size is not None else DEFAULT_FONT_SIZE
    body = max(8, min(48, body))
    clock_sz = max(10, body - 3)
    wrap_w = _wrap_cols(WIDTH - 16, body)

    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, body)
    y = 8
    for line in lines[:10]:
        for sub in textwrap.wrap(line, width=wrap_w):
            draw.text((8, y), sub, fill="white", font=font)
            bbox = draw.textbbox((8, y), sub, font=font)
            y = bbox[3] + 4
            if y > HEIGHT - 20:
                break
        if y > HEIGHT - 20:
            break
    draw.text(
        (8, HEIGHT - 22),
        _now_for_clock(tz_name).strftime("%H:%M:%S"),
        fill="#6a7380",
        font=ImageFont.truetype(font_path, clock_sz),
    )
    if device:
        device.display(image)


def idle_tick(device, font_path: str, font_size: Optional[int] = None, tz_name: Optional[str] = None):
    """Лёгкий кадр при отсутствии Redis — чтобы не залипать на чёрном при старте."""
    draw_status(
        device,
        font_path,
        ["pi_remote", "ожидание Redis…", _now_for_clock(tz_name).strftime("%Y-%m-%d")],
        font_size=font_size,
        tz_name=tz_name,
    )


def clear_screen(device) -> None:
    """Полностью чёрный кадр (перед остановкой процесса / контейнера)."""
    if not device:
        return
    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    device.display(image)
