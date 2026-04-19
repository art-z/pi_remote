# Сборка только на Raspberry Pi (aarch64 + SPI). На macOS/amd64 образ может не собраться из-за spidev.
FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    fonts-dejavu-core \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY viz.py display_agent.py ./

ENV PYTHONUNBUFFERED=1
ENV DISPLAY_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf

CMD ["python", "-u", "display_agent.py"]
