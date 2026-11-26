# Релизная версия `v1.0.0-demo` (Demo Day Release)

**Тег Git:** `v1.0.0-demo`  
**Ветка:** `feature/delivery_lab5`  
**Дата фиксации:** 2026-11-26  

---

## 1. Зафиксированные версии зависимостей (Lockfiles)

| Компонент | Файл зависимостей | Lockfile | Базовый образ |
|---|---|---|---|
| `services/extractor` | `services/extractor/requirements.txt` | `services/extractor/requirements.lock` | `python:3.12.3-slim` |
| `services/vk-publisher` | `services/vk-publisher/requirements.txt` | `services/vk-publisher/requirements.lock` | `python:3.12.3-slim` |
| `services/mailer` | `services/mailer/requirements.txt` | `services/mailer/requirements.lock` | `python:3.12.3-slim` |
| `services/page-composer` | `services/page-composer/requirements.txt` | `services/page-composer/requirements.lock` | `python:3.12.3-slim` |
| `frontend` (`site`) | `frontend/package.json` | `frontend/package-lock.json` (`pnpm-lock.yaml`) | `node:20-alpine` (Node `v20.20.2`) |

Все Python-сервисы в `Dockerfile` собираются строго из `requirements.lock` (`pip install --no-cache-dir -r requirements.lock`).

---

## 2. Зафиксированные модели LLM (Ollama)

| Роль / Tier | Имя модели | Ollama Model ID | Размер | Runtime |
|---|---|---|---|---|
| `standard` (`LLM_MODEL`) | `qwen2.5:1.5b` | `65ec06548149` | 986 MB | `ollama/ollama:0.40.13` |
| `economy` (`LLM_ECONOMY_MODEL`) | `qwen2.5:0.5b` | `a8b0c5157701` | 397 MB | `ollama/ollama:0.40.13` |

Параметры инференса зафиксированы в `services/extractor/main.py` и `compose.dev.yml`:
- `temperature=0`, `num_ctx=2048`, `num_predict=256`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=0`.
- Дневные лимиты: `DAILY_REQUEST_LIMIT=100`, `DAILY_TOKEN_LIMIT=200000`, `ECONOMY_REQUEST_LIMIT=20`, `ECONOMY_TOKEN_LIMIT=20000`.

---

## 3. Зафиксированные Docker-образы инфраструктуры

| Сервис | Образ и тег | Фактическая версия / Digest |
|---|---|---|
| `db` | `postgres:16-alpine` | PostgreSQL `16.15` (`sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`) |
| `redis` | `redis:7-alpine` | Redis `7.4.11` (`sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499`) |
| `api-gateway` | `nginx:alpine` | Nginx `1.31.6` (`sha256:c8497b180665e631ec92a5091125bec5b214f0e2b99409e30653a125b37557da`) |
| `ollama` | `ollama/ollama:0.40.13` | `sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429` |
| `prometheus` | `prom/prometheus:v2.51.0` | `sha256:5ccad477d0057e62a7cd1981ffcc43785ac10c5a35522dc207466ff7e7ec845f` |
| `loki` | `grafana/loki:2.9.6` | `sha256:6ca6e2cd3b6f45e0eb298da2920610fde63ecd8ab6c595d9c941c8559d1d9407` |
| `tempo` | `grafana/tempo:2.4.1` | `sha256:5b9c08f6d8fb43b3b72dfd1252ba4f198b11a245257bf76ee2ca13e243bac565` |
| `grafana` | `grafana/grafana:10.4.0` | `sha256:f9811e4e687ffecf1a43adb9b64096c50bc0d7a782f8608530f478b6542de7d5` |
| `alloy` | `grafana/alloy:v1.8.3` | `sha256:ab04df3936e4d71d31b6f55e0c58a7e749091f59635dd8c2bc731ba1b6c93701` |

---

## 4. Воспроизводимая сборка из тега

```bash
git checkout v1.0.0-demo
docker compose --profile ai up -d --build
# При первом запуске убедитесь, что модели загружены в Ollama:
docker compose exec ollama ollama pull qwen2.5:1.5b
docker compose exec ollama ollama pull qwen2.5:0.5b
# Проверка готовности:
curl http://localhost:8001/ready
curl http://localhost:8002/health
curl http://localhost:8003/ready
curl http://localhost:8004/ready
```
