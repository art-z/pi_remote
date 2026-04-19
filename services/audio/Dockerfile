# STT + ALSA: сборка на Raspberry Pi (aarch64). Модель Vosk не в образе — монтируйте каталог с хоста (см. models/README.md и docker-compose).
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    libasound2 \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY audio_agent.py .

ENV PYTHONUNBUFFERED=1
ENV AUDIO_MODEL_PATH=/opt/vosk-model

CMD ["python", "-u", "audio_agent.py"]
