#!/usr/bin/env python3
"""
Вентилятор с PWM на BCM13 — актуальная схема для работы на хосте без Docker.
Сервис Docker `fan` повторяет ту же логику (см. services/fan/fan_agent.py и .env).

Не запускайте этот скрипт одновременно с контейнером fan — один пин GPIO.
"""

import os
import time
from datetime import datetime

import RPi.GPIO as GPIO

FAN_PIN = 13
CHECK_INTERVAL = 5
LOG_FILE = "/home/artz/fan_log.txt"
MAX_LOG_SIZE = 100 * 1024  # 100 КБ

# Температурные пороги и соответствующие обороты
TEMP_MIN = 40.0
TEMP_MAX = 65.0

GPIO.setmode(GPIO.BCM)
GPIO.setup(FAN_PIN, GPIO.OUT)
pwm = GPIO.PWM(FAN_PIN, 25)  # 25 Гц — отличная частота для вентилятора
pwm.start(0)


def get_cpu_temp():
    res = os.popen("vcgencmd measure_temp").readline()
    temp_str = res.replace("temp=", "").replace("'C\n", "")
    return float(temp_str)


def temp_to_duty(temp):
    if temp < TEMP_MIN:
        return 0
    elif temp > TEMP_MAX:
        return 100
    else:
        # Пропорционально между MIN и MAX
        return int((temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * 100)


def log_event(temp, duty):
    now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    log_line = f"{now} Temp: {temp:.1f}°C | Fan: {duty:.0f}%\n"

    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-50:]
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line)


def main():
    try:
        while True:
            temp = get_cpu_temp()
            duty = temp_to_duty(temp)
            pwm.ChangeDutyCycle(duty)
            log_event(temp, duty)
            time.sleep(CHECK_INTERVAL)
    finally:
        pwm.stop()
        GPIO.cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
