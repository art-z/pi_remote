# Только linux/arm64 (Raspberry Pi). Сборка на самой Pi.
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fan_agent.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "fan_agent.py"]
