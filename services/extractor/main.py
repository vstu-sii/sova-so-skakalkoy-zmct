from llm_logic import LLMFields, payload as build_extraction_payload, finalize as finalize_extraction
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
import re
import secrets
import uuid
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from auth import create_access_token, decode_access_token, hash_password, verify_password
from budget import DailyBudget
from database import check_db_ready, ensure_schema, get_db
from models.event import Event
from models.expert import Expert
from models.publication import Publication
from models.subscriber import Subscriber
from telemetry import CALLS, FAILURES, LIMITS, TOKENS, UNACCOUNTED, log_event, setup, tracer


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    yield


app = FastAPI(title="extractor", lifespan=lifespan)

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
    expose_headers=["X-Extraction-Source", "X-Request-ID", "X-Trace-ID", "X-Model-Tier"],
)
setup(app)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError):
    logger.error("database_unavailable error=%s", type(exc).__name__)
    log_event("database_unavailable", reason=type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "База данных временно недоступна. Повторите запрос позже.",
            "retryable": True,
        },
        headers={"Retry-After": "5"},
    )


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


class ExtractRequest(BaseModel):
    raw_text: str


class ExtractResponse(BaseModel):
    title: str
    date: str | None = None
    location: str | None = None
    price: float | None = None


class ExpertRegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=128)
    name: str | None = Field(default=None, max_length=255)


class ExpertLoginRequest(BaseModel):
    email: str
    password: str


class ExpertOut(BaseModel):
    id: str
    email: str
    name: str
    bio: str | None = None
    avatar_url: str | None = None
    vk_connected: bool = False
    vk_group_id: str | None = None
    email_connected: bool = False
    smtp_host: str | None = None
    smtp_user: str | None = None


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    bio: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=500_000)


class VkChannelRequest(BaseModel):
    vk_group_id: str = Field(min_length=1, max_length=255)
    vk_access_token: str = Field(min_length=10, max_length=2000)


class EmailChannelRequest(BaseModel):
    smtp_host: str = Field(min_length=3, max_length=255)
    smtp_user: str = Field(min_length=3, max_length=255)
    smtp_password: str = Field(min_length=1, max_length=500)


def serialize_expert(expert: Expert) -> ExpertOut:
    return ExpertOut(
        id=str(expert.id),
        email=expert.email,
        name=expert.name,
        bio=expert.bio,
        avatar_url=expert.avatar_url,
        vk_connected=bool(expert.vk_group_id and expert.vk_access_token),
        vk_group_id=expert.vk_group_id,
        email_connected=bool(expert.smtp_host and expert.smtp_user and expert.smtp_password),
        smtp_host=expert.smtp_host,
        smtp_user=expert.smtp_user,
    )


def normalize_vk_group_id(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = re.sub(r"^https?://(?:m\.)?vk\.com/", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("/")
    m = re.match(r"^(?:club|public|event|-)?(\d+)$", cleaned, flags=re.IGNORECASE)
    if not m:
        raise HTTPException(
            status_code=422,
            detail="Укажите числовой ID сообщества ВК (например, 123456789 или club123456789)",
        )
    return m.group(1)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expert: ExpertOut


class EventCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    date: str | None = None
    location: str | None = Field(default=None, max_length=500)
    price: float | None = Field(default=None, ge=0, le=99999999.99)
    raw_text: str | None = None
    description: str | None = None
    is_online: bool = False


class PublicationOut(BaseModel):
    id: str
    channel: str
    status: str
    external_url: str | None = None
    sent_count: int = 0
    published_at: str | None = None


class EventOut(BaseModel):
    id: str
    expert_id: str
    title: str
    description: str | None = None
    raw_text: str | None = None
    date: str | None = None
    location: str | None = None
    is_online: bool = False
    price: float | None = None
    status: str
    subscribers_count: int = 0
    publications: list[PublicationOut] = Field(default_factory=list)
    created_at: str | None = None


class PublicExpertOut(BaseModel):
    name: str
    bio: str | None = None
    avatar_url: str | None = None


class PublicEventOut(BaseModel):
    id: str
    title: str
    description: str | None = None
    raw_text: str | None = None
    date: str | None = None
    location: str | None = None
    is_online: bool = False
    price: float | None = None
    status: str
    subscribers_count: int = 0
    expert: PublicExpertOut


class SubscribeRequest(BaseModel):
    event_id: str
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)


class SubscribeResponse(BaseModel):
    status: str
    id: str
    event_id: str
    name: str
    email: str
    message: str


MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# "в субботу" -> weekday index (понедельник = 0)
WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среду": 2, "среда": 2, "четверг": 3,
    "пятницу": 4, "пятница": 4, "субботу": 5, "суббота": 5,
    "воскресенье": 6,
}

TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", re.IGNORECASE)
WEEKDAY_RE = re.compile(
    r"\bв\s+(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)

PRICE_LABEL_RE = re.compile(
    r"(?:стоимость|цена)\D{0,20}?(\d[\d\s\u00a0]*(?:[.,]\d+)?)", re.IGNORECASE
)
PRICE_CURRENCY_RE = re.compile(
    r"(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей|ля|ль)?\b|р\.)", re.IGNORECASE
)
FREE_RE = re.compile(r"\bбесплатно\b|вход\s+свободный", re.IGNORECASE)

LOCATION_PATTERNS = [
    re.compile(
        r"адрес\s*[:\-–—]?\s*(.+?)(?:\.(?:\s|$)|[\n!;]|$)", re.IGNORECASE),
    re.compile(
        r"\b(в\s+(?:кафе|баре|клубе|ресторане|коворкинге|библиотеке|музее)\s+[^\n.,!;]+)", re.IGNORECASE),
    re.compile(
        r"\b(на\s+(?:Невском|[А-ЯЁ][а-яё]+(?:ом|ой|ем)\s+(?:проспекте|улице))[^\n.,!;]*)", re.IGNORECASE),
]


def _to_number(raw: str) -> float | None:
    cleaned = re.sub(r"[\s\u00a0]", "", raw).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(text: str, today: date | None = None) -> str | None:
    today = today or date.today()
    day: date | None = None

    m = DAY_MONTH_RE.search(text)
    if m:
        d, month = int(m.group(1)), MONTHS[m.group(2).lower()]
        try:
            day = date(today.year, month, d)
            if day < today:
                day = date(today.year + 1, month, d)
        except ValueError:
            day = None
    if day is None:
        w = WEEKDAY_RE.search(text)
        if w:
            target = WEEKDAYS[w.group(1).lower()]
            delta = (target - today.weekday()) % 7
            day = today + timedelta(days=delta or 7)

    t = TIME_RE.search(text)
    if day is None and t is None:
        return None
    if day is None:
        day = today
    if t:
        return datetime(day.year, day.month, day.day, int(t.group(1)), int(t.group(2))).isoformat()
    return day.isoformat()


def parse_price(text: str) -> float | None:
    for rx in (PRICE_LABEL_RE, PRICE_CURRENCY_RE):
        m = rx.search(text)
        if m:
            value = _to_number(m.group(1))
            if value is not None:
                return value
    if FREE_RE.search(text):
        return 0.0
    return None


def parse_location(text: str) -> str | None:
    for rx in LOCATION_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(1).strip(" ,:-")
    return None


def parse_title(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0].strip()
    first = first.rstrip(".!?").strip()
    return first[:120] if first else "Мероприятие"


def parse_event_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1]
    try:
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Некорректный формат даты (ожидается ISO, например 2026-11-28T19:00)",
        ) from exc


def parse_uuid(value: str, label: str = "event_id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail=f"Некорректный {label}") from exc


def serialize_event(
    event: Event,
    subscribers_count: int = 0,
    publications: list[Publication] | None = None,
) -> EventOut:
    pubs = [
        PublicationOut(
            id=str(pub.id),
            channel=pub.channel,
            status=pub.status,
            external_url=pub.external_url,
            sent_count=pub.sent_count or 0,
            published_at=pub.published_at.isoformat() if pub.published_at else None,
        )
        for pub in (publications or [])
    ]
    return EventOut(
        id=str(event.id),
        expert_id=str(event.expert_id),
        title=event.title,
        description=event.description,
        raw_text=event.raw_text,
        date=event.date.isoformat() if event.date else None,
        location=event.location_resolved or event.location_raw,
        is_online=bool(event.is_online),
        price=float(event.price_amount) if event.price_amount is not None else None,
        status=event.status,
        subscribers_count=subscribers_count,
        publications=pubs,
        created_at=event.created_at.isoformat() if event.created_at else None,
    )


logger = logging.getLogger("uvicorn.error")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "5.0"))
LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT", "150.0"))
LLM_OVERALL_TIMEOUT = float(os.getenv("LLM_OVERALL_TIMEOUT", "180.0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
MODELS = {
    "standard": os.getenv("LLM_MODEL", "qwen2.5:1.5b"),
    "economy": os.getenv("LLM_ECONOMY_MODEL", "qwen2.5:0.5b"),
}
CONTEXT_TOKENS = 2048
OUTPUT_TOKENS = 256
RESERVED_TOKENS = CONTEXT_TOKENS + OUTPUT_TOKENS
budget = DailyBudget(
    (int(os.getenv("DAILY_REQUEST_LIMIT", "100")), int(os.getenv("DAILY_TOKEN_LIMIT", "200000"))),
    (int(os.getenv("ECONOMY_REQUEST_LIMIT", "20")), int(os.getenv("ECONOMY_TOKEN_LIMIT", "20000"))),
)
tokens_to_owner = json.loads(os.getenv("EXTRACTOR_API_TOKENS", "{}"))
if not isinstance(tokens_to_owner, dict) or not all(k and isinstance(v, str) and v for k, v in tokens_to_owner.items()):
    raise ValueError("EXTRACTOR_API_TOKENS must map nonempty tokens to owner IDs")
demo_token = os.getenv("EXTRACTOR_DEMO_TOKEN")
if demo_token:
    tokens_to_owner.setdefault(demo_token, "local-demo")
bearer = HTTPBearer(auto_error=False)
llm_lock = asyncio.Lock()
extraction_source = ContextVar("extraction_source", default="unknown")


def authenticated_owner(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is not None:
        raw_token = credentials.credentials
        supplied = raw_token.encode("utf-8")
        for token, owner in tokens_to_owner.items():
            if secrets.compare_digest(supplied, token.encode("utf-8")):
                return owner
        payload = decode_access_token(raw_token)
        if payload is not None:
            return payload["sub"]
    LIMITS.labels("denied", "authorization").inc()
    log_event("authorization_denied")
    raise HTTPException(
        status_code=401,
        detail="Требуется действительный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_expert(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Expert:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Недействительный или истекший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        expert_uuid = uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    expert = db.query(Expert).filter(Expert.id == expert_uuid).first()
    if expert is None:
        raise HTTPException(
            status_code=401,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return expert


def extract_with_regex(text: str) -> dict:
    return dict(
        title=parse_title(text),
        date=parse_date(text),
        location=parse_location(text),
        price=parse_price(text),
    )


async def extract_with_llm(text: str, reservation) -> dict:
    model = MODELS[reservation.tier]
    tier = reservation.tier
    actual_tokens = None
    extraction_source.set("unknown")
    reference_date = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    version = os.getenv("AI_EXTRACTION_VERSION", "lab5-guarded")
    if version not in {"delivery_before", "lab5-guarded", "lab5-v3"}:
        raise ValueError("Unknown AI_EXTRACTION_VERSION")
    use_final = version != "delivery_before"
    request_payload = build_extraction_payload(
        text, reference_date, model, prompt_v3=version == "lab5-v3", calendar=use_final
    )
    try:
        async with asyncio.timeout(LLM_OVERALL_TIMEOUT):
            async with llm_lock:
                with CALLS.labels(tier).time(), tracer.start_as_current_span(
                    "ollama.chat", kind=SpanKind.CLIENT, record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    span.set_attribute("gen_ai.request.model", model)
                    span.set_attribute("app.budget.tier", tier)
                    span.set_attribute("app.prompt.version", version)
                    try:
                        envelope = None
                        last_exc: Exception | None = None
                        for attempt in range(LLM_MAX_RETRIES + 1):
                            try:
                                async with httpx.AsyncClient(
                                    timeout=httpx.Timeout(LLM_READ_TIMEOUT, connect=LLM_CONNECT_TIMEOUT),
                                    trust_env=False,
                                ) as client:
                                    response = await client.post(f"{OLLAMA_URL}/api/chat", json=request_payload)
                                    span.set_attribute("http.response.status_code", response.status_code)
                                    response.raise_for_status()
                                    envelope = response.json()
                                    break
                            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
                                last_exc = exc
                                is_retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
                                if attempt < LLM_MAX_RETRIES and is_retryable:
                                    log_event("llm_retry", model=model, tier=tier, attempt=attempt + 1, reason=type(exc).__name__)
                                    await asyncio.sleep(0.5 * (attempt + 1))
                                    continue
                                raise
                        if envelope is None and last_exc is not None:
                            raise last_exc
                        counts = [envelope.get("prompt_eval_count"), envelope.get("eval_count")]
                        if all(type(count) is int and count >= 0 for count in counts):
                            actual_tokens = sum(counts)
                            for direction, count in zip(("input", "output"), counts):
                                TOKENS.labels(tier, direction).inc(count)
                                span.set_attribute(f"gen_ai.usage.{direction}_tokens", count)
                        if envelope.get("done") is not True or envelope.get("done_reason") != "stop":
                            raise ValueError("incomplete response")
                        content = envelope["message"]["content"]
                        if not isinstance(content, str):
                            raise ValueError("non-string response")
                        result = LLMFields.model_validate_json(content).model_dump()
                        if use_final:
                            result = finalize_extraction(result, text, reference_date)
                            result = LLMFields.model_validate(result).model_dump()
                        extraction_source.set("ollama")
                        log_event("llm_success", model=model, tier=tier, tokens=actual_tokens)
                        return result
                    except Exception as exc:
                        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                        raise
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
        extraction_source.set("regex")
        FAILURES.labels(tier).inc()
        log_event("llm_fallback", model=model, tier=tier, reason=type(exc).__name__)
        return extract_with_regex(text)
    finally:
        if actual_tokens is None:
            UNACCOUNTED.labels(tier).inc()
        budget.settle(reservation, actual_tokens)


# === Auth endpoints (Experts only) ===

@app.post("/auth/register", response_model=AuthResponse, status_code=201)
def auth_register(req: ExpertRegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Введите корректный email")
    existing = db.query(Expert).filter(Expert.email == email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Эксперт с таким email уже зарегистрирован")

    name = (req.name or "").strip() or email.split("@", 1)[0]
    expert = Expert(
        email=email,
        password_hash=hash_password(req.password),
        name=name,
    )
    try:
        db.add(expert)
        db.commit()
        db.refresh(expert)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Эксперт с таким email уже зарегистрирован") from None

    token = create_access_token(str(expert.id), expert.email)
    return AuthResponse(
        access_token=token,
        expert=serialize_expert(expert),
    )


@app.post("/auth/login", response_model=AuthResponse)
def auth_login(req: ExpertLoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = req.email.strip().lower()
    expert = db.query(Expert).filter(Expert.email == email).first()
    if expert is None or not verify_password(req.password, expert.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    token = create_access_token(str(expert.id), expert.email)
    return AuthResponse(
        access_token=token,
        expert=serialize_expert(expert),
    )


@app.get("/auth/me", response_model=ExpertOut)
def auth_me(expert: Expert = Depends(get_current_expert)) -> ExpertOut:
    return serialize_expert(expert)


@app.put("/profile", response_model=ExpertOut)
def update_profile(
    req: ProfileUpdateRequest,
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> ExpertOut:
    name = req.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Имя должно содержать минимум 2 символа")
    expert.name = name
    expert.bio = (req.bio or "").strip() or None
    expert.avatar_url = (req.avatar_url or "").strip() or None
    db.commit()
    db.refresh(expert)
    return serialize_expert(expert)


@app.put("/profile/channels/vk", response_model=ExpertOut)
def connect_vk_channel(
    req: VkChannelRequest,
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> ExpertOut:
    group_id = normalize_vk_group_id(req.vk_group_id)
    token = req.vk_access_token.strip()
    if len(token) < 10:
        raise HTTPException(status_code=422, detail="Укажите корректный токен доступа ВК")
    expert.vk_group_id = group_id
    expert.vk_access_token = token
    db.commit()
    db.refresh(expert)
    logger.info("vk_channel_connected expert_id=%s group_id=%s", expert.id, group_id)
    return serialize_expert(expert)


@app.delete("/profile/channels/vk", response_model=ExpertOut)
def disconnect_vk_channel(
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> ExpertOut:
    expert.vk_group_id = None
    expert.vk_access_token = None
    db.commit()
    db.refresh(expert)
    logger.info("vk_channel_disconnected expert_id=%s", expert.id)
    return serialize_expert(expert)


@app.put("/profile/channels/email", response_model=ExpertOut)
def connect_email_channel(
    req: EmailChannelRequest,
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> ExpertOut:
    smtp_host = req.smtp_host.strip()
    smtp_user = req.smtp_user.strip()
    smtp_password = req.smtp_password.strip()
    if not EMAIL_RE.match(smtp_user):
        raise HTTPException(status_code=422, detail="Введите корректный email для SMTP")
    if not smtp_host or not smtp_password:
        raise HTTPException(status_code=422, detail="Заполните SMTP-сервер и пароль приложения")
    expert.smtp_host = smtp_host
    expert.smtp_user = smtp_user
    expert.smtp_password = smtp_password
    db.commit()
    db.refresh(expert)
    logger.info("email_channel_connected expert_id=%s smtp_host=%s", expert.id, smtp_host)
    return serialize_expert(expert)


@app.delete("/profile/channels/email", response_model=ExpertOut)
def disconnect_email_channel(
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> ExpertOut:
    expert.smtp_host = None
    expert.smtp_user = None
    expert.smtp_password = None
    db.commit()
    db.refresh(expert)
    logger.info("email_channel_disconnected expert_id=%s", expert.id)
    return serialize_expert(expert)


# === Extraction (Human-in-the-loop: parse only, no DB write) ===

@app.post("/extract", response_model=ExtractResponse)
async def extract(
    req: ExtractRequest,
    request: Request,
    response: Response,
    owner: str = Depends(authenticated_owner),
) -> ExtractResponse:
    text = req.raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="raw_text is empty")
    if len(text) > 1500:
        raise HTTPException(
            status_code=422, detail="Для этого прототипа допустимо до 1500 символов")
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    reservation, reason = budget.reserve(owner, RESERVED_TOKENS)
    if reservation is None:
        LIMITS.labels("rejected", reason).inc()
        log_event("budget_rejected", reason=reason, request_id=request_id)
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int((tomorrow - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Дневной бюджет исчерпан",
            headers={"Retry-After": str(retry_after)},
        )
    if reservation.tier == "economy":
        LIMITS.labels("degraded", reason).inc()
        log_event("budget_degraded", reason=reason, request_id=request_id, model=MODELS["economy"])
    parsed = await extract_with_llm(text, reservation)
    response.headers["X-Model-Tier"] = reservation.tier
    source = extraction_source.get()
    response.headers["X-Extraction-Source"] = source
    response.headers["X-Request-ID"] = request_id
    logger.info("extract_completed request_id=%s owner=%s source=%s", request_id, owner, source)
    return ExtractResponse(**parsed)


# === Events CRUD ===

@app.post("/events", response_model=EventOut, status_code=201)
def create_event(
    req: EventCreateRequest,
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> EventOut:
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название мероприятия не может быть пустым")
    event_dt = parse_event_datetime(req.date)
    location = req.location.strip() if req.location and req.location.strip() else None
    is_online = req.is_online or (location is not None and "онлайн" in location.lower())
    description = (req.description or "").strip() or (req.raw_text or "").strip() or None

    event = Event(
        expert_id=expert.id,
        title=title,
        description=description,
        raw_text=(req.raw_text or "").strip() or None,
        date=event_dt,
        location_raw=location,
        is_online=is_online,
        price_amount=req.price,
        status="draft",
    )
    try:
        db.add(event)
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=503, detail="Не удалось сохранить мероприятие") from None

    logger.info("event_created event_id=%s expert_id=%s", event.id, expert.id)
    return serialize_event(event)


@app.get("/events", response_model=list[EventOut])
def list_expert_events(
    expert: Expert = Depends(get_current_expert),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    events = (
        db.query(Event)
        .filter(Event.expert_id == expert.id)
        .order_by(Event.created_at.desc())
        .all()
    )
    if not events:
        return []

    event_ids = [ev.id for ev in events]
    sub_counts = dict(
        db.query(Subscriber.event_id, func.count(Subscriber.id))
        .filter(Subscriber.event_id.in_(event_ids))
        .group_by(Subscriber.event_id)
        .all()
    )
    pubs = (
        db.query(Publication)
        .filter(Publication.event_id.in_(event_ids))
        .order_by(Publication.created_at.desc())
        .all()
    )
    pubs_by_event: dict[uuid.UUID, list[Publication]] = {}
    for pub in pubs:
        pubs_by_event.setdefault(pub.event_id, []).append(pub)

    return [
        serialize_event(ev, subscribers_count=sub_counts.get(ev.id, 0), publications=pubs_by_event.get(ev.id, []))
        for ev in events
    ]


@app.get("/events/{event_id}", response_model=PublicEventOut)
def get_public_event(event_id: str, db: Session = Depends(get_db)) -> PublicEventOut:
    event_uuid = parse_uuid(event_id, "event_id")
    event = db.query(Event).filter(Event.id == event_uuid).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    expert = db.query(Expert).filter(Expert.id == event.expert_id).first()
    sub_count = db.query(func.count(Subscriber.id)).filter(Subscriber.event_id == event.id).scalar() or 0

    return PublicEventOut(
        id=str(event.id),
        title=event.title,
        description=event.description or event.raw_text,
        raw_text=event.raw_text,
        date=event.date.isoformat() if event.date else None,
        location=event.location_resolved or event.location_raw,
        is_online=bool(event.is_online),
        price=float(event.price_amount) if event.price_amount is not None else None,
        status=event.status,
        subscribers_count=int(sub_count),
        expert=PublicExpertOut(
            name=expert.name if expert else "Эксперт",
            bio=expert.bio if expert else None,
            avatar_url=expert.avatar_url if expert else None,
        ),
    )


# === Visitor event subscription (Public, no auth required) ===

@app.post("/subscribe", response_model=SubscribeResponse, status_code=201)
def subscribe(req: SubscribeRequest, db: Session = Depends(get_db)) -> SubscribeResponse:
    event_uuid = parse_uuid(req.event_id, "event_id")
    event = db.query(Event).filter(Event.id == event_uuid).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    name = req.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="Введите имя (минимум 2 символа)")

    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Введите корректный email")

    existing = (
        db.query(Subscriber)
        .filter(Subscriber.event_id == event.id, Subscriber.email == email)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Вы уже записаны на это мероприятие")

    subscriber = Subscriber(event_id=event.id, email=email, name=name)
    try:
        db.add(subscriber)
        db.commit()
        db.refresh(subscriber)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Вы уже записаны на это мероприятие") from None

    logger.info("subscriber_created event_id=%s subscriber_id=%s", event.id, subscriber.id)
    return SubscribeResponse(
        status="ok",
        id=str(subscriber.id),
        event_id=str(event.id),
        name=subscriber.name or name,
        email=subscriber.email,
        message="Вы успешно записались на мероприятие!",
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "extractor"}


@app.get("/ready")
def ready():
    db_ok = check_db_ready()
    if not db_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "service": "extractor", "db": "unavailable"},
            headers={"Retry-After": "5"},
        )
    return {"status": "ok", "service": "extractor", "db": "ok"}
