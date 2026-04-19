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
