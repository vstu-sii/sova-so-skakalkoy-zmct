# Окружения (Environments)

В проекте используются три окружения: **dev** (локальная разработка), **staging** (репетиция прода) и **prod** (боевой сервер).

## Различия окружений

Staging и prod используют одинаковые Docker-образы и compose-файлы, но изолированы друг от друга (разные порты, базы данных и volumes).

| Параметр | Dev (локально) | Staging | Prod |
| :--- | :--- | :--- | :--- |
| **Compose-файл** | `compose.dev.yml` | `compose.staging.yml` | `compose.dev.yml` |
| **Порт БД** | 5432 | 5433 | 5432 |
| **Порт Redis** | 6379 | 6380 | 6379 |
| **Порт Extractor** | 8001 | 8011 | 8001 |
| **Порт Page Composer** | 8002 | 8012 | 8002 |
| **Порт VK Publisher** | 8003 | 8013 | 8003 |
| **Порт Mailer** | 8004 | 8014 | 8004 |
| **Порт Site (фронтенд)** | 8010 | 8020 | 8010 |
| **Порт API Gateway** | 8000 | 8015 | 8000 |
| **Имя БД** | event_platform | event_platform_staging | event_platform |
| **Volume БД** | db_data | db_staging_data | db_data |
| **Volume Redis** | redis_data | redis_staging_data | redis_data |
| **Volume Ollama** | ollama_data | ollama_staging_data | ollama_data |
| **LLM (Ollama)** | Включена (профиль `ai`) | Включена (профиль `ai`) | Выключена (fallback на регулярки) |
| **Ограничение RAM** | Нет | Нет | 4 ГБ (риск OOM для Ollama) |

### Запуск Staging

```bash
# Без LLM
docker compose -f compose.staging.yml up -d

# С LLM
docker compose -f compose.staging.yml --profile ai up -d