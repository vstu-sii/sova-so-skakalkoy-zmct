# Сценарии отказов и отказоустойчивость (Lab 5)

**Дата проверки:** 2026-11-26  
**Ветка:** `feature/delivery_lab5`  
**Скрипт проверки:** `scripts/failure_test.py`  
**Сырые результаты прогона:** `docs/reports/failure-test-results.json`  
**Связанные ADR:** `docs/adr/001-postgresql.md`, `docs/adr/002-microservices.md`, `docs/adr/006-local-baseline-lab3.md`, `docs/adr/007-ai-extraction-iterations.md`

---

## 1. Настроенные таймауты, ретраи и пулы соединений

| Компонент | Параметр | Значение | Где настроено | Назначение |
|---|---|---|---|---|
| **PostgreSQL (SQLAlchemy)** | `connect_timeout` | `5 с` | `services/extractor/database.py`, `vk-publisher/main.py`, `mailer/main.py` | Быстрый отказ вместо зависания при падении БД |
| **PostgreSQL (SQLAlchemy)** | `pool_pre_ping` | `True` | Все 3 БД-сервиса | Автоматическое восстановление соединений после рестарта БД без рестарта приложений |
| **PostgreSQL (SQLAlchemy)** | `pool_size` / `max_overflow` / `pool_timeout` | `10 / 20 / 10 с` (`extractor`), `5 / 10 / 10 с` (`vk-publisher`, `mailer`) | Все 3 БД-сервиса | Ограничение соединений под пиковой нагрузкой |
| **Ollama LLM (`extractor`)** | `LLM_CONNECT_TIMEOUT` / `LLM_READ_TIMEOUT` / `LLM_OVERALL_TIMEOUT` | `5 с / 150 с / 180 с` | `services/extractor/main.py` | Ограничение времени вызова и очереди (ADR-006) |
| **Ollama LLM (`extractor`)** | `LLM_MAX_RETRIES` | `1` (backoff `0.5 с`) | `services/extractor/main.py` | Ретрай кратковременного сетевого сбоя / `5xx` перед fallback |
| **VK API (`vk-publisher`)** | `VK_TIMEOUT` / connect / `VK_MAX_RETRIES` | `20 с / 5 с / 1` (backoff `0.5 с`) | `services/vk-publisher/main.py` | Устойчивость к кратковременному сбою `api.vk.com` |
| **SMTP (`mailer`)** | `SMTP_TIMEOUT` / `SMTP_MAX_RETRIES` | `15 с / 1` (backoff `0.5 с`) | `services/mailer/main.py` | Ретрай при сбое подключения (только если письма ещё не начали уходить — без дублей) |
| **Readiness / Liveness** | `GET /health` vs `GET /ready` | `/health` → `200`; `/ready` → `SELECT 1` (`200` или `503`) | `extractor`, `vk-publisher`, `mailer` | Разделение живости процесса и готовности принимать трафик к БД |

---

## 2. Матрица сценариев отказов (фактическая проверка на живом стеке)

| ID | Сценарий отказа | Ожидаемое поведение (по ADR / требованиям) | Фактический результат прогона | HTTP-код (не 500!) | Статус |
|---|---|---|---|---:|---|
| **F1** | **Отказ LLM-провайдера (`docker compose stop ollama`)** | 1 ретрай, затем штатная деградация на regex-парсер, заголовок `X-Extraction-Source: regex`, инкремент метрики `extractor_llm_failures_total` | `POST /extract` вернул распарсенные `title`, `date: 2026-12-25T19:00:00`, `location`, `price: 1800.0` за `8.52 с`, `x-extraction-source: regex`, `extractor_llm_failures_total` вырос | **200** | PASS |
| **F2.1** | **Отказ БД (`docker compose stop db`) — liveness/readiness** | `/health` остаётся `200`, `/ready` на всех БД-сервисах отдаёт `503` с `Retry-After: 5` | `extractor /health` = `200` (`21 мс`); `/ready` на `extractor`, `vk-publisher`, `mailer` = `503` (`4.0–4.2 с`, `Retry-After: 5`) | **200 / 503** | PASS |
| **F2.2** | **Отказ БД — пользовательские эндпоинты** | Глобальный `@app.exception_handler(SQLAlchemyError)` возвращает структурированный `503` с понятным сообщением и `retryable: true` | `GET /events/{id}` (`2.30 с`), `POST /subscribe` (`2.29 с`), `POST /auth/login` (`4.01 с`), `POST /publish` (`4.02 с`), `POST /send` (`4.00 с`) — все вернули `503` + `Retry-After: 5` | **503** | PASS |
| **F2.3** | **Восстановление БД (`docker compose start db`)** | Автоматическое восстановление без перезапуска сервисов (`pool_pre_ping=True`) | `GET /ready` перешёл в `200` за **1.13 с**, `GET /events/{id}` сразу вернул `200` | **200** | PASS |
| **F3** | **Исчерпание дневного бюджета LLM (`DailyBudget`)** | Деградация `standard` (`qwen2.5:1.5b`) → `economy` (`qwen2.5:0.5b`, `X-Model-Tier: economy`) → отказ `429` с заголовком `Retry-After` (до полуночи UTC) | Подтверждено модульным и HTTP-тестом `services/extractor/test_delivery.py` (`[200, 200, 429, 200]`, изоляция по владельцам) | **200 → 429** | PASS |
| **F4** | **Отказ внешнего канала VK API (невалидный токен / обрыв TLS)** | Ретрай 1 раз, запись `status='failed'` и `error_message` в `publications`, возврат `502` на фронтенд | `POST /publish` вернул `502` с диагностическим описанием ошибки, запись `failed` сохранена в БД | **502** | PASS |
| **F5** | **Отказ внешнего SMTP-сервера (порт 465/587 заблокирован сетью)** | Ретрай 1 раз, запись `status='failed'` и `error_message` в `publications`, возврат `502`; при пустых SMTP-настройках — безопасный fallback в `mock`-режим | Проверено вживую при блокировке порта 465 (`502 Bad Gateway`, понятная ошибка в UI); без SMTP — `200 OK` (`mode: mock`) | **502 / 200** | PASS |
| **F6** | **Нарушение границ ввода и авторизации** | Чёткие `4xx`-коды без падения сервиса | Без токена → `401`, пустой `raw_text` → `400`, `>1500` символов → `422`, невалидный UUID → `404`, повторная запись того же email → `409` | **400/401/404/409/422** | PASS |

---

## 3. Деградация по ADR

1. **ADR-006 (локальная LLM в ограниченных ресурсах):**
   - `POST /extract` не обращается к БД (Human-in-the-loop сохранение вынесено в `POST /events`), поэтому извлечение продолжает работать даже при кратковременной недоступности PostgreSQL.
   - При недоступности Ollama, таймауте (`>180 с`) или невалидном JSON от модели `extract_with_llm()` автоматически переключается на детерминированный `extract_with_regex()` (`X-Extraction-Source: regex`) — эксперт получает предзаполненную форму подтверждения и может доредактировать поля вручную.
2. **Защита от перерасхода токенов/CPU:**
   - `DailyBudget` ограничивает запросы и токены отдельно для каждого владельца (JWT `sub` / API-токен): сначала мягкая деградация на `qwen2.5:0.5b` (`economy`), затем `429 Too Many Requests` с `Retry-After`.
3. **Отказ каналов доставки (`vk-publisher`, `mailer`):**
   - Сбой одного канала изолирован (микросервисная архитектура, ADR-002): недоступность VK API или SMTP не мешает созданию мероприятий и записи участников (`/event/[id]`, `POST /subscribe`).

---

## 4. Как воспроизвести проверку сценариев отказов

```bash
docker compose --profile ai up -d
python scripts/failure_test.py
```
Скрипт автоматически восстанавливает остановленные контейнеры (`ollama`, `db`) в блоках `finally` и сохраняет отчёт в `docs/reports/failure-test-results.json`.
