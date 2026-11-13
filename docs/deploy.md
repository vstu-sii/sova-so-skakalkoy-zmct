# Деплой (Deploy)

## Текущее состояние

### Продакшн (Prod)

Приложение развернуто на удалённом сервере (VPS). 
На текущий момент обновление кода на сервере производится **вручную** через SSH.

*   **Прод-URL:** `https://tanya-lab.88-87-92-145.sslip.io/`
*   **Как обновить вручную:**

```bash
ssh root@<IP_СЕРВЕРА> -p <ПОРТ_SSH>
cd /путь/до/проекта/event-platform
git pull origin main
docker compose -f compose.dev.yml up -d --build
