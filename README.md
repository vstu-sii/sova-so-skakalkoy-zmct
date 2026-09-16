# event-platform

[![CI](https://github.com/vstu-sii/sova-so-skakalkoy-zmct/actions/workflows/ci.yml/badge.svg)](https://github.com/vstu-sii/sova-so-skakalkoy-zmct/actions/workflows/ci.yml)

Платформа для экспертов: один анонс — сайт мероприятия + пост во ВК + email-рассылка.

## О проекте

Эксперт пишет анонс мероприятия один раз. Система:

- извлекает из текста дату, место и цену (`services/extractor`);
- собирает страницу мероприятия из готовых блоков (`services/page-composer`);
- публикует пост в VK-группе эксперта (`services/vk-publisher`);
- делает email-рассылку по подписчикам (`services/mailer`).

Результат: эксперт не тратит часы на ручное размещение, данные о мероприятии на всех площадках совпадают, под каждую площадку форматирование подбирается индивидуально.

## Стек

- **Backend:** Python, FastAPI
- **Frontend:** JavaScript-фреймворк (выбор в процессе)
- **База данных:** PostgreSQL 16
- **ИИ:** LLM API
- **Инфраструктура:** Docker, Docker Compose
- **CI:** GitHub Actions

## Быстрый старт

### Требования

- Docker Desktop 24.0+
- Docker Compose 2.20+
- Git

### Роли

| Имя | GitHub | Роль |
|-----|--------|------|
| Анастасия Юмаева | @ | Product / VO |
| Кизименко Алёна | @AlenKizimenko | AI engineer |
| Ларина Татьяна | @Thanoss-blip | Delivery |
| Казакова Мария | @OVENAsHome | Quality & safety |

### Запуск

```bash
git clone https://github.com/vstu-sii/sova-so-skakalkoy-zmct.git
cd sova-so-skakalkoy-zmct
cp .env.example .env
docker compose -f compose.dev.yml up -d
