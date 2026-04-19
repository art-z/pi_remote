"""Упрощённая отрисовка ST7789: режим pulse (как в prev/visualizer) и status (текст).
Размеры как в prev/display.py — через DISPLAY_WIDTH / DISPLAY_HEIGHT (по умолчанию 240)."""

from __future__ import annotations

import colorsys
import os
import textwrap
import time
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH = int(os.getenv("DISPLAY_WIDTH", "240"))
HEIGHT = int(os.getenv("DISPLAY_HEIGHT", "240"))
CENTER = (WIDTH // 2, HEIGHT // 2)


class PulseVisualizer:
    def __init__(self, device, font_path: str):
        self.text = ""
        self.color = "white"
        self.device = device
        self.volume_level = 0
        self.phase = 0.0
        self.state = "idle"
        self.font = ImageFont.truetype(font_path, 18)
        self.font_small = ImageFont.truetype(font_path, 16)

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

        display_text = self.text
        lines: list[str] = []
        for paragraph in display_text.split("\n"):
            for line in textwrap.wrap(paragraph, width=26) if paragraph else [""]:
                if line:
                    lines.append(line)
        if len(lines) > 6:
            lines = lines[:6]

        y = HEIGHT - 10 - 20 * len(lines) if lines else HEIGHT - 30
        for line in lines:
            draw.text((10, y), line, fill=self.color, font=self.font_small)
            bbox = draw.textbbox((10, y), line, font=self.font_small)
            y = bbox[3] + 2

        if self.device:
            self.device.display(image)


def draw_status(device, font_path: str, lines: list[str]):
    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 17)
    y = 8
    for line in lines[:10]:
        for sub in textwrap.wrap(line, width=28):
            draw.text((8, y), sub, fill="white", font=font)
            bbox = draw.textbbox((8, y), sub, font=font)
            y = bbox[3] + 4
            if y > HEIGHT - 20:
                break
        if y > HEIGHT - 20:
            break
    draw.text(
        (8, HEIGHT - 22),
        datetime.now().strftime("%H:%M:%S"),
        fill="#6a7380",
        font=ImageFont.truetype(font_path, 14),
    )
    if device:
        device.display(image)


def idle_tick(device, font_path: str):
    """Лёгкий кадр при отсутствии Redis — чтобы не залипать на чёрном при старте."""
    draw_status(
        device,
        font_path,
        ["pi_remote", "ожидание Redis…", time.strftime("%Y-%m-%d")],
    )
