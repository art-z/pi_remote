"""
PWM-вентилятор по температуре (как scripts/fan_control_pwm.py на хосте).
Пишет состояние в Redis — веб /api/status подмешивает поле fan.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time

import RPi.GPIO as GPIO
import redis
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fan")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FAN_STATE_KEY = os.getenv("FAN_STATE_KEY", "fan:state")

FAN_GPIO = int(os.getenv("FAN_GPIO", "13"))
TEMP_MIN = float(os.getenv("FAN_TEMP_MIN", "40"))
TEMP_MAX = float(os.getenv("FAN_TEMP_MAX", "65"))
PWM_HZ = float(os.getenv("FAN_PWM_HZ", "25"))
CHECK_INTERVAL = float(os.getenv("FAN_CHECK_INTERVAL_SEC", "5"))


def get_cpu_temp() -> float:
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=2)
        return float(out.replace("temp=", "").strip().rstrip("'C"))
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        log.debug("vcgencmd: %s — sysfs", e)
    path = os.getenv("CPU_TEMP_SYSFS", "/sys/class/thermal/thermal_zone0/temp")
    with open(path, encoding="utf-8") as f:
        raw = int(f.read().strip())
    return raw / 1000.0 if raw > 1000 else float(raw)


def temp_to_duty(temp: float) -> int:
    if temp < TEMP_MIN:
        return 0
    if temp > TEMP_MAX:
        return 100
    return int((temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * 100)


def main() -> None:
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(FAN_GPIO, GPIO.OUT)
    pwm = GPIO.PWM(FAN_GPIO, PWM_HZ)
    pwm.start(0)

    stop = False

    def _handle_sig(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    log.info(
        "PWM BCM %s @ %.1f Hz, duty 0–100%% for temp %.1f–%.1f°C",
        FAN_GPIO,
        PWM_HZ,
        TEMP_MIN,
        TEMP_MAX,
    )

    try:
        while not stop:
            temp = get_cpu_temp()
            duty = temp_to_duty(temp)
            pwm.ChangeDutyCycle(duty)

            payload = {
                "mode": "pwm",
                "duty_percent": duty,
                "on": duty > 0,
                "temp_c": round(temp, 1),
                "gpio": FAN_GPIO,
                "pwm_hz": PWM_HZ,
                "temp_min": TEMP_MIN,
                "temp_max": TEMP_MAX,
            }
            r.set(FAN_STATE_KEY, json.dumps(payload, ensure_ascii=False))

            time.sleep(CHECK_INTERVAL)
    finally:
        try:
            pwm.stop()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
        log.info("Выход")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("%s", e)
        sys.exit(1)
