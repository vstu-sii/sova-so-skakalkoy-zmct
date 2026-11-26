#!/bin/bash
# Скрипт отката на предыдущую версию
# Использование: ./rollback.sh

echo "🔄 Откат на предыдущий коммит..."
cd /workspace/event-platform || cd /путь/до/проекта/event-platform

# Откатываемся на 1 коммит назад
git checkout HEAD~1

# Пересобираем и перезапускаем
docker compose -f compose.dev.yml up -d --build

echo "✅ Откат завершен. Текущая версия:"
git log --oneline -1