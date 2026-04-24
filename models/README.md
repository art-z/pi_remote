# Модели для сервиса `audio` (Vosk)

Модель **не** кладётся в Git: скачайте архив и распакуйте в этот каталог на **хосте** (малина или машина, где крутится Docker).

## Ссылка на скачивание (small-ru, быстрая для Pi)

**Прямая ссылка (ZIP):**

https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip

Страница со всеми моделями: https://alphacephei.com/vosk/models

## Куда положить

Нужна **распакованная** папка `vosk-model-small-ru-0.22` с файлами модели внутри (как после `unzip`).

Рекомендуемый путь от корня репозитория:

```text
pi_remote/models/vosk-model-small-ru-0.22/
  am/
  conf/
  graph/
  …
```

Так по умолчанию смонтирует `docker-compose.yml` (`./models/vosk-model-small-ru-0.22` → `/opt/vosk-model` в контейнере).

## Пример с хоста

Из каталога **`models/`** в корне проекта:

```bash
cd models
curl -fLO 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'
unzip -q vosk-model-small-ru-0.22.zip
rm -f vosk-model-small-ru-0.22.zip
```

Должна появиться папка `vosk-model-small-ru-0.22`.

Другой путь на диске — задайте в `.env` переменную **`VOSK_MODEL_HOST_DIR`** (абсолютный или относительно каталога с `docker-compose.yml`).

### `Permission denied` / `checkdir error: cannot create …/graph`

Значит, текущий пользователь **не может создавать каталоги** в `models/` (или в уже частично созданной `vosk-model-small-ru-0.22/`). Частые причины: репозиторий или `models/` созданы от **root** (`sudo git clone`, распаковка через `sudo`), либо каталог только для чтения.

**Проверка:**

```bash
ls -la models
ls -ld models models/vosk-model-small-ru-0.22 2>/dev/null
```

**Исправить владельца** (подставьте путь к своему клону `pi_remote`):

```bash
sudo chown -R "$(whoami):$(whoami)" /path/to/pi_remote/models
# при необходимости весь репозиторий:
# sudo chown -R "$(whoami):$(whoami)" /path/to/pi_remote
```

Удалите обломки неудачной распаковки и повторите `unzip`:

```bash
cd /path/to/pi_remote/models
rm -rf vosk-model-small-ru-0.22
unzip -q vosk-model-small-ru-0.22.zip   # или снова curl, если архив удалили
```

**Обходной путь:** распаковать в домашний каталог (туда обычно есть права), затем перенести:

```bash
cd models
curl -fLO 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip'
unzip -q vosk-model-small-ru-0.22.zip -d "$HOME"
rm -f vosk-model-small-ru-0.22.zip
mv "$HOME/vosk-model-small-ru-0.22" .
```

Если `mv` в `models/` снова пишет «Permission denied», сначала сделайте `chown` на каталог `models`, как в блоке выше.
