# pi_remote

Raspberry Pi 4 Model B Rev 1.4

Linux ai 5.15.0-1079-raspi #82-Ubuntu SMP PREEMPT Tue May 27 04:20:55 UTC 2025 aarch64 aarch64 aarch64 aarch64 GNU/Linux

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

## Часть 1. Docker: стек, поднятие, работа, железо

Здесь — непосредственно **проект pi_remote в контейнерах**: что за сервисы, как поднять, как пользоваться, что нужно от платы.

### Стек

**nginx** (статика и reverse proxy на порт 80) → **FastAPI** (один worker uvicorn) → внутренняя сеть `pi_net`. Рядом: **Redis** (очереди и pub/sub для дисплея), **sync-worker** (исходящая синхронизация JSON на внешний сервер по `REMOTE_SYNC_URL`), **display** (ST7789, `luma.lcd`), **fan** (PWM на BCM **13**, как в `scripts/fan_control_pwm.py`).

Переменные окружения — из `**.env`** (шаблон `**.env.example**`). Если на машине нет SPI/GPIO, закомментируйте сервисы `**display**` и/или `**fan**` в `**docker-compose.yml**`.

### Требования и железо

- **Docker** и **Docker Compose v2**.
- Сборка образов **на самой Pi** (aarch64) или `docker buildx build --platform linux/arm64`.
- Для `**display`**: доступ к `**/dev/spidev0.0**`, `**/dev/gpiomem**` (см. `prev/docker-compose.yml`).
- Для `**fan**`: GPIO (контейнер с `privileged` и `/dev/gpiomem`), пин — в `.env` (`FAN_GPIO`).

### Поднятие стека

1. Конфиг: `cp .env.example .env`, при необходимости заполните `REMOTE_SYNC_URL`, токены, пороги вентилятора и параметры дисплея (как в `prev/display.py`: 240×240, SPI 80 МГц, поворот 180° → в luma `**DISPLAY_ROTATE=2**`).
2. Весь стек сразу (веб, API, Redis, sync-worker, **дисплей**, **вентилятор**):
  ```bash
   docker compose up -d --build
  ```
   На том же GPIO нельзя одновременно держать хостовый скрипт вентилятора и контейнер `**fan**` — см. **часть 2**.

### Работа: веб и API

- В браузере: `http://<IP_малины>/` — метрики и форма управления дисплеем.
- Состояние вентилятора в ответе `**GET /api/status`** (поле `**fan**`, в т.ч. `**duty_percent**` при PWM), если работает сервис `**fan**` и пишет ключ в Redis.

### Метрики в контейнере

API в контейнере видит **cgroup**-лимиты Docker. Для «системных» метрик всей малины можно позже включить `**network_mode: host`** только для `**api**` или собирать метрики на хосте — текущая схема проще для Pi.

Температура: сначала `**vcgencmd**`, при отсутствии — sysfs (`CPU_TEMP_SYSFS` в `.env`).

### Очередь и внешний сервер

- События в Redis `**LIST**` (`SYNC_QUEUE_KEY`, по умолчанию `sync:outbound`).
- `**sync-worker**` делает **POST** на полный URL `**REMOTE_SYNC_URL`** с телом JSON и опционально `**Authorization: Bearer <REMOTE_SYNC_TOKEN>**`.
- Ручная постановка: `**POST /api/sync/enqueue**` (через nginx: `**/api/sync/enqueue**`).
- Автотелеметрия: `**SYNC_AUTO=true**` — периодически в очередь кладётся снимок метрик (`type: telemetry`).

### Расширение стека (аудио, видео, изображения)

- Новые сервисы — в `**services/**`, сеть `**pi_net**` в `**docker-compose.yml**`.
- Очереди и сигналы — через **Redis** (как `**display:notify`**).
- Тяжёлые воркеры — отдельные сервисы с `**profiles**`, чтобы базовый стек оставался лёгким на четырёх ядрах Pi 4.

---

## Часть 2. Дополнительно и необязательно. Хост, старые сервисы, уборка

Здесь — всё, что **не обязательно** для работы Compose, но нужно при миграции с «голого» хоста: отключить дубли, освободить GPIO/SPI, убрать старые юниты.

### Вентилятор: хост (`scripts/fan_control_pwm.py`) и Docker (`fan`)

Не запускайте одновременно **хостовый** PWM-скрипт и контейнер `**fan`** — один пин (**BCM 13** по умолчанию).

Перед `docker compose up` отключите хостовый вентилятор:

- **systemd:** `systemctl list-units --type=service --all | grep -i fan` → `sudo systemctl stop <имя>` и при необходимости `sudo systemctl disable <имя>`;
- **cron / @reboot:** `crontab -l` — удалите строки с `fan_control` / `fan_control_pwm`;
- **процесс:** `pgrep -af fan` — завершите лишний процесс.

Подсветка ST7789 в luma по умолчанию на **GPIO 18**, вентилятор на **13** — конфликта нет. Если меняли `**DISPLAY_GPIO_LIGHT`**, не совмещайте его с `**FAN_GPIO**`.

### Как убрать лишние сервисы на хосте

Имеется в виду всё, что **не** должно работать параллельно с Docker (старые ассистенты, отдельный nginx, свои скрипты на тех же пинах). Схема: **найти источник → остановить → убрать автозапуск → при необходимости удалить пакет или юнит**.

**1. systemd (службы и таймеры)**

- Включённые юниты: `systemctl list-unit-files --state=enabled`
- Поиск: `systemctl list-units --type=service --all | grep -i <слово>`
- Остановить: `sudo systemctl stop <имя>.service`
- Отключить автозапуск: `sudo systemctl disable <имя>.service`
- Остановить и отключить: `sudo systemctl disable --now <имя>.service`
- Запретить запуск до `unmask`: `sudo systemctl mask <имя>.service` / `sudo systemctl unmask <имя>.service`
- Таймеры: `systemctl list-timers --all` → `sudo systemctl disable --now <имя>.timer`

**2. cron**

- Пользователь: `crontab -l`, правка `crontab -e`
- Система: `/etc/crontab`, `/etc/cron.d/`, `/etc/cron.hourly` и т.д. — правьте осознанно

**3. Процессы без systemd**

- Поиск: `pgrep -af <фрагмент>` или `ps aux | grep <имя>`
- Завершение: `kill <PID>`, в крайнем случае `kill -9 <PID>`

**4. Старые контейнеры Docker**

- `docker ps` / `docker ps -a`
- В каталоге проекта: `docker compose down` (без `-v`, если нужны тома Redis)
- Осторожно: `docker system prune` — смотрите `docker system prune --help`

**5. Пакеты apt**

- `dpkg -l | grep <слово>`
- `sudo apt purge <пакет>` или `sudo apt remove <пакет>`

**6. Конфликт с pi_remote по железу**

Если на хосте уже заняты **GPIO / SPI / PWM**, сначала освободите их способами выше, **потом** поднимайте стек (или закомментируйте `**display`** / `**fan**` в `**docker-compose.yml**`, пока тестируете без железа). Два процесса не должны открывать один пин или `**/dev/spidev0.0**`.
 