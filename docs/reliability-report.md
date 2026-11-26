# Отчёт надёжности: нагрузка, отказы, аптайм (Lab 5)

**Релизная версия:** `v1.0.0-demo` (ветка `feature/delivery_lab5`)  
**Дата формирования:** 2026-11-26  
**Детальные артефакты:**
- Нагрузочное тестирование: [`docs/load-testing.md`](load-testing.md) · [`docs/reports/load-test-results.json`](reports/load-test-results.json)
- Сценарии отказов: [`docs/failure-scenarios.md`](failure-scenarios.md) · [`docs/reports/failure-test-results.json`](reports/failure-test-results.json)
- Релизная фиксация и lockfiles: [`RELEASE.md`](../RELEASE.md)

---

## 1. Сводка готовности к Demo Day

| Критерий | Целевой показатель | Факт | Статус |
|---|---|---|---|
| **Пропускная способность API (UC-04 + UC-01)** | ≥ 50 RPS, ошибки < 1% | **402–421 RPS**, **0% ошибок** (1 500 запросов при `c=5..100`) | OK |
| **Латентность API (`c=20`, Demo Day)** | p95 < 500 мс | **p50 = 46.2 мс**, **p95 = 82.2 мс**, **p99 = 109.7 мс** | OK |
| **Латентность фронтенда (`site`, `c=20`)** | p95 < 1 000 мс | **131.2 RPS**, **p50 = 102.6 мс**, **p95 = 339.0 мс** | OK |
| **AI-извлечение (`POST /extract`, Ollama `qwen2.5:1.5b`)** | Стабильная работа + fallback | **0.10–0.14 RPS** (`p50 = 8.1 с` при `c=1`, `15.0 с` при `c=3`), fallback на regex при отказе Ollama | OK |
| **Отказ БД / LLM / внешних каналов** | 0 необработанных HTTP `500` | **0 ошибок `500`**; штатные `200` (regex), `503` + `Retry-After: 5` (БД), `502` (VK/SMTP), `429` (бюджет) | OK |
| **Восстановление после падения БД** | Автоматическое, < 10 с | **1.13 с** (`pool_pre_ping=True`, без перезапуска контейнеров) | OK |
| **Фиксация версий и воспроизводимость** | `git tag` + lockfiles + модели | Тег `v1.0.0-demo`, `requirements.lock` × 4, `package-lock.json`, `qwen2.5:1.5b` (`65ec06548149`) | OK |

---

## 2. Нагрузка (резюме)

- Проведено ступенчатое тестирование по смешанному профилю UC-04 / UC-01 (`70%` чтение `/events/{id}`, `15%` запись `/subscribe`, `10%` дашборд `/events`, `5%` `/compose`) от `c=5` до `c=100`, а также отдельные прогоны для SSR Next.js (`site`), `vk-publisher` и Ollama LLM.
- **Предел CRUD/API:** насыщение на уровне **~420 RPS** (один воркер `uvicorn` + пул БД `10+20`), 0% ошибок на всех ступенях.
- **Предел LLM:** **~6–8 извлечений/мин** (последовательная очередь `OLLAMA_NUM_PARALLEL=1` защищает память по ADR-006). Подробный разбор узких мест — в [`docs/load-testing.md`](load-testing.md).

---

## 3. Отказоустойчивость (резюме)

Проведены живые fault-injection тесты (`scripts/failure_test.py`) и модульные тесты бюджета (`services/extractor/test_delivery.py` — 4/4 OK):
- **Остановка Ollama (`F1`):** 1 ретрай, затем штатная деградация на regex (`HTTP 200`, `X-Extraction-Source: regex`, 8.52 с).
- **Остановка PostgreSQL (`F2`):** `/health` остаётся `200`, `/ready` и все БД-эндпоинты возвращают `503 Service Unavailable` с `Retry-After: 5`. После старта БД сервисы возвращаются в `200` за **1.13 с** без перезапуска.
- **Ошибки внешних каналов (`F4`, `F5`):** `502 Bad Gateway` с сохранением `status='failed'` и `error_message` в таблице `publications`.
- **Границы ввода и авторизации (`F3`/`F6`):** корректные `400 / 401 / 404 / 409 / 422`.

---

## 4. Мониторинг, алерты и аптайм

### 4.1. Метрики сервисов (прямой срез `/metrics` после прогонов)

| Метрика | Значение | Порог алерта / оценка |
|---|---:|---|
| `extractor_llm_tokens_total` (`input` + `output`, `standard`) | `2 538 + 474 = 3 012` | Порог алерта `delivery-token-spike`: `> 20 000 / 5 мин` → **OK (алерт не сработал)** |
| `extractor_limit_decisions_total{decision="rejected"}` | `0` | **OK** (перерасхода бюджета нет) |
| `extractor_limit_decisions_total{decision="denied",reason="authorization"}` | `1` | Ожидаемо (тест `F3` без токена) |
| `extractor_llm_failures_total{tier="standard"}` | `2` | Ожидаемо (тест `F1` с остановкой Ollama, оба запроса обработаны через regex) |
| `page-composer` `http_requests_total{status="2xx"}` | `75` | **0 ошибок** |
| `vk-publisher` `http_requests_total{status="2xx"}` | `40` | **0 ошибок** под нагрузкой; 2 штатных `503/502` в fault-injection |
| Необработанные HTTP `500` по всем сервисам | `0` | **OK** |

### 4.2. Статус контейнеров и аптайм

- **Core-сервисы (локальный прогон ~2.5 ч):**
  - `db` (PostgreSQL 16.15), `redis` (7.4.11), `ollama` (0.40.13), `api-gateway` (Nginx), `alloy` — **100% аптайм** (кроме контролируемых остановок `ollama`/`db` в тесте `failure_test.py` на 10–15 с).
  - `extractor`, `page-composer`, `vk-publisher`, `mailer`, `site` — стабильно `Up` после сборки, все `/health` и `/ready` возвращают `200 OK`, 0 падений/OOM.
- **Состояние мониторинга (Grafana / Prometheus / Loki / Tempo):**
  - Конфигурация мониторинга (`monitoring/prometheus/prometheus.yml`, `monitoring/grafana/provisioning/alerting/usage.yaml`, дашборд `monitoring/grafana/dashboards/main.json`) валидна, метрики экспортируются всеми 4 сервисами на `/metrics`, алерт `delivery-token-spike` в норме (3 012 < 20 000 токенов).
  - *Примечание по локальной Windows-среде:* на локальной машине ранее скачанные слои образов `prometheus`/`loki`/`tempo`/`grafana` завершались с `exec format error` (повреждённый локальный кэш образа). Для чистого запуска мониторинга на целевом сервере/машине выполните перевыкачивание образов:
    ```bash
    docker compose rm -sf prometheus loki tempo grafana
    docker compose pull prometheus loki tempo grafana
    docker compose up -d prometheus loki tempo grafana
    ```
- **Прод-аптайм за 7 дней:** на локальном стенде зафиксирован непрерывный тестовый прогон (~2.5 ч) без сбоев; для демонстрации 7-дневного аптайма прода на Demo Day достаточно выгрузить скриншот панели `Uptime & Latency` из Grafana (`http://<prod-host>:3002`) по задеплоенному тегу `v1.0.0-demo`.
