# pi_remote

Raspberry Pi 4 Model B Rev 1.4

PRETTY_NAME="Ubuntu 22.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
VERSION="22.04.5 LTS (Jammy Jellyfish)"
VERSION_CODENAME=jammy
ID=ubuntu
ID_LIKE=debian
HOME_URL="[https://www.ubuntu.com/](https://www.ubuntu.com/)"
SUPPORT_URL="[https://help.ubuntu.com/](https://help.ubuntu.com/)"
BUG_REPORT_URL="[https://bugs.launchpad.net/ubuntu/](https://bugs.launchpad.net/ubuntu/)"
PRIVACY_POLICY_URL="[https://www.ubuntu.com/legal/terms-and-policies/privacy-policy](https://www.ubuntu.com/legal/terms-and-policies/privacy-policy)"
UBUNTU_CODENAME=jammy

processor       : 0
BogoMIPS        : 108.00
Features        : fp asimd evtstrm crc32 cpuid
CPU implementer : 0x41
CPU architecture: 8
CPU variant     : 0x0
CPU part        : 0xd08
CPU revision    : 3

processor       : 1
BogoMIPS        : 108.00
Features        : fp asimd evtstrm crc32 cpuid
CPU implementer : 0x41
CPU architecture: 8
CPU variant     : 0x0
CPU part        : 0xd08
CPU revision    : 3

processor       : 2
BogoMIPS        : 108.00
Features        : fp asimd evtstrm crc32 cpuid
CPU implementer : 0x41
CPU architecture: 8
CPU variant     : 0x0
CPU part        : 0xd08
CPU revision    : 3

processor       : 3
BogoMIPS        : 108.00
Features        : fp asimd evtstrm crc32 cpuid
CPU implementer : 0x41
CPU architecture: 8
CPU variant     : 0x0
CPU part        : 0xd08
CPU revision    : 3

Hardware        : BCM2835
Revision        : b03114
Serial          : 10000000fe35d4e2
Model           : Raspberry Pi 4 Model B Rev 1.4
uname -a

---

## Docker: стек, поднятие, работа, железо

**проект pi_remote в контейнерах**: что за сервисы, как поднять, как пользоваться, что нужно от платы.

### Стек

**nginx** (статика и reverse proxy на порт 80) → **FastAPI** (один worker uvicorn) → внутренняя сеть `pi_net`. Рядом: **Redis** (очереди и pub/sub для дисплея), **sync-worker** (исходящая синхронизация JSON на внешний сервер по `REMOTE_SYNC_URL`), **display** (ST7789, `luma.lcd`), **fan** (PWM на BCM **13**, как в `scripts/fan_control_pwm.py`), **audio** (микрофон ALSA → **Vosk** small-ru, текст в `display:state` / `display:notify`).

Переменные окружения — из `**.env`** (шаблон `**.env.example`**). Если на машине нет SPI/GPIO, закомментируйте сервисы `**display**` и/или `**fan**` в `**docker-compose.yml**`.

### Требования и железо

- **Docker** и **Docker Compose v2**.
- Сборка образов **на самой Pi** (aarch64) или `docker buildx build --platform linux/arm64`.
- Для `**display`**: доступ к `**/dev/spidev0.0`**, `**/dev/gpiomem**` Распиновка ST7789, подсветка и замечания по GPIO: `**services/display/README.md**`.
- Для `**fan**`: GPIO (контейнер с `privileged` и `/dev/gpiomem`), пин — в `.env` (`FAN_GPIO`).
- Для `**audio**`: `/dev/snd`, в `.env` задайте `AUDIO_ALSA_DEVICE` (на хосте: `arecord -l`). Подробно про `plughw:1,0` и проверку микрофона — `**services/audio/README.md**`. Без микрофона закомментируйте сервис `**audio**` в `**docker-compose.yml**`.

### Поднятие стека

1. Конфиг: `cp .env.example .env`, при необходимости заполните `REMOTE_SYNC_URL`, токены, пороги вентилятора и параметры дисплея.
2. Весь стек сразу (веб, API, Redis, sync-worker, **дисплей**, **вентилятор**):
  ```bash
   docker compose up -d --build
  ```
   На том же GPIO нельзя одновременно держать хостовый скрипт вентилятора и контейнер `**fan**` — см. **часть 2**.

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

