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
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "http://localhost:8010").rstrip("/")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="vk-publisher")
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


class PublishRequest(BaseModel):
    event_id: str


def format_vk_post(event: dict) -> str:
    lines = [f"🔥 {event['title']}"]
    if event.get("date"):
        dt = event["date"]
        formatted_dt = dt.strftime("%d.%m.%Y в %H:%M") if hasattr(dt, "strftime") else str(dt)
        lines.append(f"📅 Когда: {formatted_dt}")
    location = event.get("location_resolved") or event.get("location_raw")
    if location:
        lines.append(f"📍 Где: {location}")
    elif event.get("is_online"):
        lines.append("📍 Формат: Онлайн")
    price = event.get("price_amount")
    if price is not None:
        price_val = float(price)
        price_str = "Бесплатно" if price_val == 0 else f"{int(price_val) if price_val.is_integer() else price_val} ₽"
        lines.append(f"💳 Стоимость: {price_str}")
    description = event.get("description") or event.get("raw_text")
    if description:
        lines.append("")
        lines.append(description.strip())
    if event.get("expert_name"):
        lines.append("")
        lines.append(f"Ведущий: {event['expert_name']}")
    lines.append(f"👉 Записаться: {PUBLIC_SITE_URL}/event/{event['id']}")
    return "\n".join(lines)


@app.post("/publish")
def publish(req: PublishRequest, db: Session = Depends(get_db)) -> dict:
    try:
        event_uuid = uuid.UUID(req.event_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Некорректный event_id") from exc

    row = db.execute(
        text(
            """
            SELECT e.id, e.title, e.description, e.raw_text, e.date,
                   e.location_raw, e.location_resolved, e.is_online,
                   e.price_amount, e.status, ex.name AS expert_name
            FROM events e
            LEFT JOIN experts ex ON ex.id = e.expert_id
            WHERE e.id = :event_id
            """
        ),
        {"event_id": str(event_uuid)},
    ).mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    post_text = format_vk_post(dict(row))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_id = uuid.uuid4()
    external_url = f"https://vk.com/wall-mock_{str(event_uuid)[:8]}_{str(pub_id)[:6]}"

    logger.info(
        "\n========== [VK-PUBLISHER MOCK POST] ==========\n"
        "Event ID: %s\n"
        "URL: %s\n"
        "----------------------------------------------\n"
        "%s\n"
        "==============================================",
        event_uuid,
        external_url,
        post_text,
    )

    try:
        db.execute(
            text(
                """
                INSERT INTO publications (id, event_id, channel, status, external_url, published_at)
                VALUES (:id, :event_id, 'vk', 'published', :external_url, :published_at)
                """
            ),
            {
                "id": str(pub_id),
                "event_id": str(event_uuid),
                "external_url": external_url,
                "published_at": now,
            },
        )
        db.execute(
            text(
                """
                UPDATE events
                SET status = 'published', updated_at = :updated_at
                WHERE id = :event_id
                """
            ),
            {"updated_at": now, "event_id": str(event_uuid)},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save VK publication for event_id=%s", event_uuid)
        raise HTTPException(status_code=503, detail="Не удалось сохранить статус публикации") from exc

    return {
        "status": "published",
        "publication_id": str(pub_id),
        "event_id": str(event_uuid),
        "channel": "vk",
        "external_url": external_url,
        "published_at": now.isoformat(),
        "post_text": post_text,
        "message": "Пост опубликован в ВК (тестовый режим)",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "vk-publisher"}
