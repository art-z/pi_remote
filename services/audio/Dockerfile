# STT + ALSA: сборка на Raspberry Pi (aarch64). Модель small-ru (~45 MB) — быстрый русский Vosk.
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    alsa-utils \
    libasound2 \
    && wget -q https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip -O /tmp/vosk-ru.zip \
    && unzip -q /tmp/vosk-ru.zip -d /opt \
    && mv /opt/vosk-model-small-ru-0.22 /opt/vosk-model \
    && rm -f /tmp/vosk-ru.zip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY audio_agent.py .

ENV PYTHONUNBUFFERED=1
ENV AUDIO_MODEL_PATH=/opt/vosk-model

CMD ["python", "-u", "audio_agent.py"]
