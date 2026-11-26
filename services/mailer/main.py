from publication_guard import authorize
from datetime import datetime, timezone
from email.message import EmailMessage
import logging
import os
import smtplib
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://event_platform:changeme@db:5432/event_platform",
)
SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "15.0"))
SMTP_MAX_RETRIES = int(os.getenv("SMTP_MAX_RETRIES", "1"))

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


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError):
    logger.error("mailer_db_unavailable error=%s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "База данных временно недоступна. Повторите попытку позже.",
            "retryable": True,
        },
        headers={"Retry-After": "5"},
    )


class SendRequest(BaseModel):
    event_id: str
    approved: bool = Field(default=False, strict=True)
    recipients: list[str] | None = None


def parse_smtp_host_port(raw_host: str, default_port: int = 465) -> tuple[str, int]:
    cleaned = raw_host.strip()
    if ":" in cleaned:
        host_part, port_part = cleaned.rsplit(":", 1)
        try:
            return host_part.strip(), int(port_part.strip())
        except ValueError:
            pass
    return cleaned, default_port


def get_smtp_config(event_row: dict | None = None) -> dict | None:
    if event_row:
        ex_host = (event_row.get("expert_smtp_host") or "").strip()
        ex_user = (event_row.get("expert_smtp_user") or "").strip()
        ex_pass = (event_row.get("expert_smtp_password") or "").strip()
        if ex_host and ex_user and ex_pass:
            host, port = parse_smtp_host_port(ex_host, default_port=465)
            return {
                "host": host,
                "port": port,
                "user": ex_user,
                "password": ex_pass,
                "sender": ex_user,
                "source": "expert_profile",
            }

    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not (host and user and password):
        return None
    try:
        default_port = int(os.getenv("SMTP_PORT", "465").strip() or "465")
    except ValueError:
        default_port = 465
    parsed_host, port = parse_smtp_host_port(host, default_port=default_port)
    sender = os.getenv("SMTP_FROM", "").strip() or user
    return {
        "host": parsed_host,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "source": "env",
    }


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
        price_str = (
            "Бесплатно"
            if price_val == 0
            else f"{int(price_val) if price_val.is_integer() else price_val} ₽"
        )
        lines.append(f"Стоимость: {price_str}")
    lines.extend(["", "Ждём вас!"])
    return "\n".join(lines)


def send_via_smtp(
    smtp_cfg: dict,
    subject: str,
    event: dict,
    recipients_map: dict[str, str | None],
) -> tuple[list[str], list[str]]:
    sent: list[str] = []
    failed: list[str] = []

    smtp_cls = smtplib.SMTP_SSL if smtp_cfg["port"] == 465 else smtplib.SMTP
    last_exc: Exception | None = None
    for attempt in range(SMTP_MAX_RETRIES + 1):
        try:
            with smtp_cls(smtp_cfg["host"], smtp_cfg["port"], timeout=SMTP_TIMEOUT) as server:
                if smtp_cfg["port"] != 465:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                server.login(smtp_cfg["user"], smtp_cfg["password"])

                for recipient_email, subscriber_name in recipients_map.items():
                    msg = EmailMessage()
                    msg["From"] = smtp_cfg["sender"]
                    msg["To"] = recipient_email
                    msg["Subject"] = subject
                    msg.set_content(
                        format_email_body(event, subscriber_name),
                        subtype="plain",
                        charset="utf-8",
                    )
                    try:
                        server.send_message(msg)
                        sent.append(recipient_email)
                        logger.info("[MAILER SMTP] Sent email to %s (subject=%s)", recipient_email, subject)
                    except Exception as exc:
                        failed.append(f"{recipient_email}: {exc}")
                        logger.warning("[MAILER SMTP] Failed to send to %s: %s", recipient_email, exc)
            return sent, failed
        except (OSError, smtplib.SMTPException) as exc:
            last_exc = exc
            if attempt < SMTP_MAX_RETRIES and not sent:
                logger.warning("smtp_retry attempt=%s error=%s", attempt + 1, type(exc).__name__)
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    return sent, failed


@app.post("/send")
def send(req: SendRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    authorize(req.event_id, req.approved, request.headers.get("Authorization", ""), db)
    try:
        event_uuid = uuid.UUID(req.event_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Некорректный event_id") from exc

    event_row = db.execute(
        text(
            """
            SELECT e.id, e.title, e.description, e.date, e.location_raw, e.location_resolved,
                   e.is_online, e.price_amount,
                   ex.smtp_host AS expert_smtp_host,
                   ex.smtp_user AS expert_smtp_user,
                   ex.smtp_password AS expert_smtp_password
            FROM events e
            LEFT JOIN experts ex ON ex.id = e.expert_id
            WHERE e.id = :event_id
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
    smtp_cfg = get_smtp_config(event)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pub_id = uuid.uuid4()

    sent_recipients: list[str] = []
    error_message: str | None = None
    mode = "smtp" if smtp_cfg else "mock"

    if not recipients_map:
        logger.info(
            "[MAILER %s] Event ID=%s (%s): нет подписчиков для рассылки",
            mode.upper(),
            event_uuid,
            event["title"],
        )
        pub_status = "no_subscribers"
    elif smtp_cfg is not None:
        try:
            sent_recipients, failed = send_via_smtp(smtp_cfg, subject, event, recipients_map)
            if failed:
                error_message = "; ".join(failed)
            pub_status = "sent" if sent_recipients else "failed"
        except Exception as exc:
            error_message = f"SMTP error: {exc}"
            pub_status = "failed"
            logger.exception("[MAILER SMTP] Connection/auth failed for event_id=%s", event_uuid)
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
            sent_recipients.append(recipient_email)
        pub_status = "sent"

    sent_count = len(sent_recipients)

    try:
        db.execute(
            text(
                """
                INSERT INTO publications (id, event_id, channel, status, sent_count, error_message, published_at)
                VALUES (:id, :event_id, 'email', :status, :sent_count, :error_message, :published_at)
                """
            ),
            {
                "id": str(pub_id),
                "event_id": str(event_uuid),
                "status": pub_status,
                "sent_count": sent_count,
                "error_message": error_message,
                "published_at": now,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to save mailer publication for event_id=%s", event_uuid)
        raise HTTPException(status_code=503, detail="Не удалось сохранить статус рассылки") from exc

    if pub_status == "failed":
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось отправить письма через SMTP: {error_message}",
        )

    if sent_count == 0:
        message = "Нет записавшихся участников для рассылки"
    elif mode == "smtp":
        message = f"Рассылка выполнена через SMTP: отправлено {sent_count} писем"
    else:
        message = f"Рассылка выполнена: отправлено {sent_count} писем (тестовый режим)"

    return {
        "status": pub_status,
        "mode": mode,
        "publication_id": str(pub_id),
        "event_id": str(event_uuid),
        "channel": "email",
        "sent_count": sent_count,
        "recipients": sent_recipients,
        "published_at": now.isoformat(),
        "message": message,
    }


@app.get("/health")
def health() -> dict:
    smtp_enabled = get_smtp_config() is not None
    return {"status": "ok", "service": "mailer", "smtp_configured": smtp_enabled}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "service": "mailer", "db": "ok"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "service": "mailer", "db": "unavailable"},
            headers={"Retry-After": "5"},
        )
