# pi_remote

Raspberry Pi 4 Model B Rev 1.4 Debian GNU/Linux 13 (Trixie).

---

## Docker: стек, поднятие, работа, железо
 
### Стек

**nginx** (статика и reverse proxy на порт 80) → **FastAPI** (один worker uvicorn) → внутренняя сеть `pi_net`. Рядом: **Redis** (очереди и pub/sub для дисплея), **sync-worker** (исходящая синхронизация JSON на внешний сервер по `REMOTE_SYNC_URL`), **display** (ST7789, `luma.lcd`), **fan** (PWM на BCM **13**, как в `scripts/fan_control_pwm.py`), **audio** (микрофон ALSA → **Vosk** small-ru, текст в `display:state` / `display:notify`).

Переменные окружения — из `**.env`** (шаблон `**.env.example`**). Если на машине нет SPI/GPIO, закомментируйте сервисы `**display**` и/или `**fan**` в `**docker-compose.yml**`.

### Требования и железо

- **Docker** и **Docker Compose v2**.
- Сборка образов **на самой Pi** (aarch64) или `docker buildx build --platform linux/arm64`.
- Для `**display`**: доступ к `**/dev/spidev0.0`**, `**/dev/gpiomem**` Распиновка ST7789, подсветка и замечания по GPIO: `**services/display/README.md**`.
- Для `**fan**`: GPIO (контейнер с `privileged` и `/dev/gpiomem`), пин — в `.env` (`FAN_GPIO`).
- Для `**audio**`: `/dev/snd`, модель Vosk с диска (скачивание и путь: **`models/README.md`**, по умолчанию `./models/vosk-model-small-ru-0.22`), при другом каталоге — `VOSK_MODEL_HOST_DIR` в `.env`; микрофон — `AUDIO_ALSA_DEVICE` (`arecord -l`). Подробно про ALSA — `**services/audio/README.md**`. Без микрофона закомментируйте сервис `**audio**` в `**docker-compose.yml**`.

### Установка Docker на Pi (Debian GNU/Linux 13 Trixie, arm64)

Ниже — официальный репозиторий Docker для [Debian](https://docs.docker.com/engine/install/debian/): на Pi 4 с Trixie архитектура будет **arm64** (`aarch64`). Кодовое имя дистрибутива (`trixie`) берётся из `/etc/os-release`.

1. Зависимости и ключ репозитория:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

2. Подключить стабильный канал Docker (`dpkg --print-architecture` → `arm64` на этой платформе):

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

3. Установить Engine, CLI, containerd, **Buildx** и **Compose v2** (плагин `docker compose`):

```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

4. Проверка и запуск без `sudo` (после этого нужен новый вход в сессию SSH или `newgrp docker`):

```bash
sudo systemctl enable --now docker
docker --version
docker compose version
sudo usermod -aG docker "$USER"
```

Если команда `docker` пишет «permission denied», выйдите из SSH и зайдите снова (или выполните `newgrp docker` в текущей оболочке).

### Поднятие стека

1. Конфиг: `cp .env.example .env`, при необходимости заполните `REMOTE_SYNC_URL`, токены, пороги вентилятора и параметры дисплея.
2. Весь стек сразу (веб, API, Redis, sync-worker, **дисплей**, **вентилятор**):
  ```bash
   docker compose up -d --build
  ```
  
### Работа: веб и API

- В браузере: `http://<IP_малины>/` — метрики и форма управления дисплеем.
- Состояние вентилятора в ответе `**GET /api/status`** (поле `**fan`**, в т.ч. `**duty_percent**` при PWM), если работает сервис `**fan**` и пишет ключ в Redis.

### Метрики в контейнере

API в контейнере видит **cgroup**-лимиты Docker. Для «системных» метрик всей малины можно позже включить `**network_mode: host`** только для `**api`** или собирать метрики на хосте — текущая схема проще для Pi.

Температура: сначала `**vcgencmd**`, при отсутствии — sysfs (`CPU_TEMP_SYSFS` в `.env`).

### Очередь и внешний сервер

- События в Redis `**LIST**` (`SYNC_QUEUE_KEY`, по умолчанию `sync:outbound`).
- `**sync-worker**` делает **POST** на полный URL `**REMOTE_SYNC_URL`** с телом JSON и опционально `**Authorization: Bearer <REMOTE_SYNC_TOKEN>`**.
- Ручная постановка: `**POST /api/sync/enqueue**` (через nginx: `**/api/sync/enqueue**`).
- Автотелеметрия: `**SYNC_AUTO=true**` — периодически в очередь кладётся снимок метрик (`type: telemetry`).

### Расширение стека (аудио, видео, изображения)

- Новые сервисы — в `**services/**`, сеть `**pi_net**` в `**docker-compose.yml**`.
- Очереди и сигналы — через **Redis** (как `**display:notify`**).
- Тяжёлые воркеры — отдельные сервисы с `**profiles`**, чтобы базовый стек оставался лёгким на четырёх ядрах Pi 4.

---

