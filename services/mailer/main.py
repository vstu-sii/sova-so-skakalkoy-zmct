from datetime import datetime, timezone
import logging
import os
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://event_platform:changeme@db:5432/event_platform",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="mailer")
Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(
    app, include_in_schema=False
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8010",
        "http://localhost:8020",
        "http://localhost:8080",
        "http://site:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SendRequest(BaseModel):
    event_id: str
    recipients: list[str] | None = None


def format_email_body(event: dict, subscriber_name: str | None) -> str:
    greeting = f"Здравствуйте, {subscriber_name}!" if subscriber_name else "Здравствуйте!"
    lines = [
        greeting,
        "",
        f"Напоминаем о мероприятии «{event['title']}».",
    ]
    if event.get("date"):
        dt = event["date"]
        formatted_dt = dt.strftime("%d.%m.%Y в %H:%M") if hasattr(dt, "strftime") else str(dt)
        lines.append(f"Дата и время: {formatted_dt}")
    location = event.get("location_resolved") or event.get("location_raw")
    if location:
        lines.append(f"Место: {location}")
    elif event.get("is_online"):
        lines.append("Формат: Онлайн")
    price = event.get("price_amount")
    if price is not None:
        price_val = float(price)
        price_str = "Бесплатно" if price_val == 0 else f"{int(price_val) if price_val.is_integer() else price_val} ₽"
        lines.append(f"Стоимость: {price_str}")
    lines.extend(["", "Ждём вас!"])
    return "\n".join(lines)


@app.post("/send")
def send(req: SendRequest, db: Session = Depends(get_db)) -> dict:
    try:
        event_uuid = uuid.UUID(req.event_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Некорректный event_id") from exc

    event_row = db.execute(
        text(
            """
            SELECT id, title, description, date, location_raw, location_resolved,
                   is_online, price_amount
            FROM events
            WHERE id = :event_id
            """
        ),
        {"event_id": str(event_uuid)},
    ).mappings().first()

    if event_row is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    event = dict(event_row)
    subscriber_rows = db.execute(
        text(
            """
            SELECT email, name
            FROM subscribers
            WHERE event_id = :event_id
            ORDER BY registered_at ASC
            """
        ),
        {"event_id": str(event_uuid)},
    ).mappings().all()

    recipients_map: dict[str, str | None] = {
        row["email"]: row["name"] for row in subscriber_rows
    }
    for extra_email in req.recipients or []:
        cleaned = extra_email.strip().lower()
        if cleaned and cleaned not in recipients_map:
            recipients_map[cleaned] = None

    subject = f"Напоминание: {event['title']}".replace("\r", " ").replace("\n", " ")

    if not recipients_map:
        logger.info(
            "[MAILER MOCK] Event ID=%s (%s): нет подписчиков для рассылки",
            event_uuid,
            event["title"],
        )
    else:
        for recipient_email, subscriber_name in recipients_map.items():
            body = format_email_body(event, subscriber_name)
            logger.info(
                "\n========== [MAILER MOCK EMAIL] ==========\n"
                "To: %s\n"
                "Subject: %s\n"
                "-----------------------------------------\n"
                "%s\n"
                "=========================================",
                recipient_email,
                subject,
                body,
            )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_id = uuid.uuid4()
    sent_count = len(recipients_map)
    pub_status = "sent" if sent_count > 0 else "no_subscribers"

    try:
        db.execute(
            text(
                """
                INSERT INTO publications (id, event_id, channel, status, sent_count, published_at)
                VALUES (:id, :event_id, 'email', :status, :sent_count, :published_at)
                """
            ),
            {
                "id": str(pub_id),
                "event_id": str(event_uuid),
                "status": pub_status,
                "sent_count": sent_count,
                "published_at": now,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save mailer publication for event_id=%s", event_uuid)
        raise HTTPException(status_code=503, detail="Не удалось сохранить статус рассылки") from exc

    message = (
        f"Рассылка выполнена: отправлено {sent_count} писем (тестовый режим)"
        if sent_count > 0
        else "Нет записавшихся участников для рассылки"
    )
    return {
        "status": pub_status,
        "publication_id": str(pub_id),
        "event_id": str(event_uuid),
        "channel": "email",
        "sent_count": sent_count,
        "recipients": list(recipients_map.keys()),
        "published_at": now.isoformat(),
        "message": message,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mailer"}
