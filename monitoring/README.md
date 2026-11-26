# Delivery, лабораторная 4

Запускайте из корня event-platform. Команды ниже рассчитаны на **CMD**,
Docker Desktop в режиме Linux containers и WSL2. При переносе в существующий
проект сохраняйте его `.env` и имя Compose-проекта. Имя по умолчанию —
`event-platform`. Если проект раньше назывался иначе, установите
`set "COMPOSE_PROJECT_NAME=старое-имя"`, чтобы использовать прежние volumes
и чтобы Alloy видел нужные контейнеры.

## 1. Диагностика exec format error

```cmd
wsl --status
docker info --format "{{.OSType}}/{{.Architecture}}"
docker compose version
docker compose -f compose.dev.yml config --quiet
```

Docker Engine должен показывать `linux`. Если показывает `windows`,
в меню Docker Desktop выберите **Switch to Linux containers**, затем включите
WSL2 backend. В готовом compose у Prometheus, Loki, Tempo, Grafana и Alloy
указано `platform: linux/amd64`. На ARM64 для этих образов нужна поддержка
эмуляции amd64. Если ошибка возникает уже на команде `docker info`, сначала
нужно починить сам Docker Desktop/WSL, прежде чем менять конфигурацию сервисов.

Если ошибку выдаёт контейнер, удалите только контейнеры мониторинга и
загрузите их образы заново. Удаление образов необязательно, если они
используются другими проектами. Команды сохраняют именованные volumes.

```cmd
docker compose -f compose.dev.yml rm -s -f prometheus loki tempo grafana alloy
docker image rm prom/prometheus:v2.51.0 grafana/loki:2.9.6 grafana/tempo:2.4.1 grafana/grafana:10.4.0 grafana/alloy:v1.8.3
docker compose -f compose.dev.yml pull prometheus loki tempo grafana alloy
docker image inspect --format "{{.Os}}/{{.Architecture}}" prom/prometheus:v2.51.0 grafana/loki:2.9.6 grafana/tempo:2.4.1 grafana/grafana:10.4.0 grafana/alloy:v1.8.3
docker compose -f compose.dev.yml up -d --force-recreate prometheus loki tempo grafana alloy
docker compose -f compose.dev.yml ps
docker compose -f compose.dev.yml logs --tail 80 prometheus loki tempo grafana alloy
```

Ожидаемая архитектура каждого образа — `linux/amd64`. При её совпадении
с конфигурацией возьмите первую строку ошибки и проверьте, какой бинарник
или entrypoint её выдаёт. `exec format error` сам по себе не доказывает
несовместимость образа. Общий `docker system prune` для этого не нужен.
См. [WSL2 в Docker Desktop](https://docs.docker.com/desktop/features/wsl/)
и [platform в Compose](https://docs.docker.com/reference/compose-file/services/#platform).

## 2. Запуск и быстрый тест лимитов

Создайте `.env` только если его ещё нет. Для демонстрации установите свой
случайный секрет вместо `REPLACE_WITH_RANDOM_TOKEN`. Переменные `set`
действуют в текущем окне CMD и переопределяют значения из `.env`.

```cmd
if not exist .env copy .env.example .env
set "EXTRACTOR_DEMO_TOKEN=REPLACE_WITH_RANDOM_TOKEN"
set "DAILY_REQUEST_LIMIT=2"
set "ECONOMY_REQUEST_LIMIT=1"
docker compose -f compose.dev.yml config --quiet
docker compose -f compose.dev.yml up -d ollama prometheus loki tempo grafana alloy
docker compose -f compose.dev.yml exec -T ollama ollama pull qwen2.5:1.5b
docker compose -f compose.dev.yml exec -T ollama ollama pull qwen2.5:0.5b
docker compose -f compose.dev.yml up -d --build extractor page-composer vk-publisher mailer site
docker compose -f compose.dev.yml ps
curl.exe -f http://127.0.0.1:8001/health
curl.exe -f http://127.0.0.1:8001/metrics
timeout /t 20 /nobreak
docker compose -f compose.dev.yml exec -T extractor python check_delivery.py --standard 2 --economy 1
```

Скрипт проверяет `401` без действительного токена, два ответа
`200 standard ollama`, затем `200 economy ollama` и `429` с Retry-After.
Он считает regex fallback ошибкой smoke-теста, поскольку там модель не
ответила. Скрипт создаёт несколько учебных карточек в БД. Запускайте его
в учебной среде с пустым бюджетом. Перед повтором можно пересоздать только
extractor, чтобы сбросить его счётчики.

Для демонстрации 101-го запроса задайте `DAILY_REQUEST_LIMIT=100` и
`ECONOMY_REQUEST_LIMIT=1`, пересоздайте extractor и передайте скрипту
`--standard 100 --economy 1`. Это более долгий тест. Если первым исчерпан
токен-бюджет, экономика включится раньше. Для теста именно счётчика запросов
установите `DAILY_TOKEN_LIMIT=230400`, чтобы хватило резервов на 100 вызовов.
После демонстрации верните обычные значения и пересоздайте extractor.

Одиночный запрос в CMD:

```cmd
curl.exe -i -X POST http://127.0.0.1:8001/extract -H "Authorization: Bearer %EXTRACTOR_DEMO_TOKEN%" -H "Content-Type: application/json" -d "{\"raw_text\":\"Workshop on November 20, 2026, at 18:00. Free admission.\"}"
```

В интерфейсе на порту 8010 тот же токен можно ввести в поле «Токен доступа».
Для нескольких пользователей настройте в `.env`
`EXTRACTOR_API_TOKENS='{"сильный-токен-А":"expert-a","сильный-токен-Б":"expert-b"}'`.
Храните токены на сервере и передавайте по HTTPS при внешнем доступе.
Заголовок X-User-Id не определяет владельца.

## 3. Проверка наблюдаемости

- Prometheus Targets на `http://127.0.0.1:9090/targets`. Четыре FastAPI
  сервиса должны стать UP. Метрики видны после ближайшего scrape.
- Grafana на `http://127.0.0.1:3002`. Логин admin, пароль из
  `GRAFANA_ADMIN_PASSWORD` при первом запуске или пароль существующего
  Grafana volume. В свежей учебной среде по умолчанию admin.
  Откройте **Delivery → Event Platform — Delivery**. Панели Requests,
  Latency, Tokens, Errors показывают RPS и лимиты, p95, токены по тарифу
  и направлению, HTTP-ошибки и fallback.
- В Explore выберите Loki и запрос
  `{service="extractor"} |~ "budget_degraded|budget_rejected|authorization_denied"`.
  После теста должны появиться события со `trace_id`. Alloy читает логи
  контейнеров и передаёт их Loki. Доступ к Docker socket является
  привилегированным, поэтому этот вариант коллектора предназначен
  для доверенной учебной машины. [Сбор Docker-логов в Alloy](https://grafana.com/docs/alloy/latest/monitor/monitor-docker-containers/).
- В Explore → Tempo найдите Trace ID из заголовка `X-Trace-ID` или
  нажмите ссылку TraceID рядом с JSON-логом. Ожидаются родительский span
  `POST /extract` и дочерний `ollama.chat` с моделью и токенами.
  У отказов 401/429 нет дочернего LLM span. Экспорт OTLP HTTP идёт на
  внутренний `http://tempo:4318/v1/traces` пакетами, подождите несколько секунд.
  [Приём OTLP в контейнерах](https://grafana.com/docs/tempo/latest/set-up-for-tracing/instrument-send/set-up-collector/grafana-alloy/).
- В Alerting → Alert rules есть `Ollama token consumption spike`.
  Условие: более 20 000 токенов за 5 минут в течение 2 минут.
  Для учебного теста временно замените число в evaluator и summary на 1,
  задайте `for: 0m`, пересоздайте Grafana и отправьте запрос после scrape.
  Подождите одну минуту. После проверки восстановите порог. Уведомления
  наружу требуют отдельного contact point.
  [Провижининг правил Grafana](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/).

При недоступности Ollama см. `docker compose -f compose.dev.yml logs extractor ollama`
и `docker stats --no-stream`. Оба размера модели должны быть скачаны,
на сервере одновременно загружается одна модель. Успешный fallback
регулярками в таком случае отмечен в метриках и заголовке.

## 4. Как работают ограничения

Сутки считаются по UTC. Основной тариф — до 100 вызовов и 200 000 токенов
на пользователя. Резервный — до 20 вызовов и 20 000 токенов.
Счётчик атомарно резервирует верхнюю оценку 2304 токена перед запросом:
контекст 2048 и вывод 256. После ответа резерв заменяется фактическими
счётчиками Ollama. При отсутствии статистики резерв удерживается.
Поэтому переход может произойти, когда оставшегося бюджета недостаточно
для полного резерва. Отдельно видно неизвестный расход.

Хранилище находится в памяти процесса. Запускайте один worker и одну
реплику. Рестарт сбрасывает бюджет. Для устойчивых лимитов на нескольких
репликах понадобится общее атомарное хранилище, например Redis.
Модель получает только текст, дату отсчёта и схему. Выбор модели,
авторизация и запись события выполняются приложением. Инструменты,
доступ к секретам и полномочия публикации модели не передаются.

## 5. Состав сдачи

- compose.dev.yml и .env.example — службы, сеть, переменные и volumes.
- monitoring — конфиги Prometheus, Loki, Alloy, Tempo, Grafana и alert.
- services/extractor — main.py, budget.py, telemetry.py, requirements.txt,
  локальный тест и check_delivery.py.
- services/page-composer, services/vk-publisher, services/mailer —
  инструментирование FastAPI и зависимости.
- frontend — ввод токена в форме и отправка Authorization.

Локальные проверки extractor можно запустить в контейнере командой
`docker compose -f compose.dev.yml exec -T extractor python -m unittest -v test_delivery.py`.
В ней HTTP Ollama и сохранение подменены. Проверку работающих Grafana,
Loki, Tempo и PostgreSQL выполняет отдельная последовательность выше.
