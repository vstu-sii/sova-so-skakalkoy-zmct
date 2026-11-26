from datetime import datetime, timezone
import logging
import os
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://event_platform:changeme@db:5432/event_platform",
)
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "http://localhost:8010").rstrip("/")
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")
VK_TIMEOUT = float(os.getenv("VK_TIMEOUT", "20.0"))
VK_MAX_RETRIES = int(os.getenv("VK_MAX_RETRIES", "1"))

connect_args = {"connect_timeout": 5} if DATABASE_URL.startswith("postgresql") else {}
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=10,
    connect_args=connect_args,
)
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


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError):
    logger.error("vk_publisher_db_unavailable error=%s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "База данных временно недоступна. Повторите попытку позже.",
            "retryable": True,
        },
        headers={"Retry-After": "5"},
    )


class PublishRequest(BaseModel):
    event_id: str


def resolve_vk_credentials(event_row: dict) -> tuple[str, str] | None:
    group_id = (event_row.get("vk_group_id") or os.getenv("VK_GROUP_ID", "")).strip()
    token = (event_row.get("vk_access_token") or os.getenv("VK_ACCESS_TOKEN", "")).strip()
    if not (group_id and token):
        return None
    clean_group_id = group_id.lstrip("-")
    return clean_group_id, token


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
        price_str = (
            "Бесплатно"
            if price_val == 0
            else f"{int(price_val) if price_val.is_integer() else price_val} ₽"
        )
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


def publish_to_vk_api(group_id: str, access_token: str, message: str) -> str:
    last_exc: Exception | None = None
    payload = None
    for attempt in range(VK_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                "https://api.vk.com/method/wall.post",
                data={
                    "owner_id": f"-{group_id}",
                    "from_group": 1,
                    "message": message,
                    "access_token": access_token,
                    "v": VK_API_VERSION,
                },
                timeout=httpx.Timeout(VK_TIMEOUT, connect=5.0),
            )
            response.raise_for_status()
            payload = response.json()
            break
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            is_retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
            if attempt < VK_MAX_RETRIES and is_retryable:
                logger.warning("vk_api_retry attempt=%s error=%s", attempt + 1, type(exc).__name__)
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    if payload is None and last_exc is not None:
        raise last_exc
    if "error" in payload:
        err = payload["error"]
        code = err.get("error_code", "?")
        msg = err.get("error_msg", "Неизвестная ошибка VK API")
        raise RuntimeError(f"VK API error {code}: {msg}")
    post_id = payload.get("response", {}).get("post_id")
    if not post_id:
        raise RuntimeError("VK API не вернул post_id")
    return f"https://vk.com/wall-{group_id}_{post_id}"


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
                   e.price_amount, e.status,
                   ex.name AS expert_name,
                   ex.vk_group_id AS vk_group_id,
                   ex.vk_access_token AS vk_access_token
            FROM events e
            LEFT JOIN experts ex ON ex.id = e.expert_id
            WHERE e.id = :event_id
            """
        ),
        {"event_id": str(event_uuid)},
    ).mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    event = dict(row)
    post_text = format_vk_post(event)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_id = uuid.uuid4()
    creds = resolve_vk_credentials(event)

    mode = "vk_api" if creds else "mock"
    external_url: str | None = None
    error_message: str | None = None
    pub_status = "published"

    if creds is not None:
        group_id, access_token = creds
        try:
            external_url = publish_to_vk_api(group_id, access_token, post_text)
            logger.info("[VK-PUBLISHER API] Published event_id=%s url=%s", event_uuid, external_url)
        except Exception as exc:
            pub_status = "failed"
            error_message = str(exc)
            logger.exception("[VK-PUBLISHER API] Publish failed for event_id=%s", event_uuid)
    else:
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
                INSERT INTO publications (id, event_id, channel, status, external_url, error_message, published_at)
                VALUES (:id, :event_id, 'vk', :status, :external_url, :error_message, :published_at)
                """
            ),
            {
                "id": str(pub_id),
                "event_id": str(event_uuid),
                "status": pub_status,
                "external_url": external_url,
                "error_message": error_message,
                "published_at": now,
            },
        )
        if pub_status == "published":
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

    if pub_status == "failed":
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось опубликовать пост в ВК: {error_message}",
        )

    return {
        "status": "published",
        "mode": mode,
        "publication_id": str(pub_id),
        "event_id": str(event_uuid),
        "channel": "vk",
        "external_url": external_url,
        "published_at": now.isoformat(),
        "post_text": post_text,
        "message": (
            f"Пост опубликован в ВК: {external_url}"
            if mode == "vk_api"
            else "Пост опубликован в ВК (тестовый режим — подключите сообщество в Кабинете)"
        ),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "vk-publisher"}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "service": "vk-publisher", "db": "ok"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "service": "vk-publisher", "db": "unavailable"},
            headers={"Retry-After": "5"},
        )
