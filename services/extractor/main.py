import re
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080", "http://site:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    raw_text: str


class RegisterRequest(BaseModel):
    event_id: str
    email: str
    name: str


class ExtractResponse(BaseModel):
    title: str
    date: str | None = None
    location: str | None = None
    price: float | None = None


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
DAY_MONTH_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", re.IGNORECASE)
WEEKDAY_RE = re.compile(r"\bв\s+(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)

PRICE_LABEL_RE = re.compile(
    r"(?:стоимость|цена)\D{0,20}?(\d[\d\s ]*(?:[.,]\d+)?)", re.IGNORECASE
)
PRICE_CURRENCY_RE = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей|ля|ль)?\b|р\.)", re.IGNORECASE
)
FREE_RE = re.compile(r"\bбесплатно\b|вход\s+свободный", re.IGNORECASE)

LOCATION_PATTERNS = [
    re.compile(r"адрес\s*[:\-–—]?\s*(.+?)(?:\.(?:\s|$)|[\n!;]|$)", re.IGNORECASE),
    re.compile(r"\b(в\s+(?:кафе|баре|клубе|ресторане|коворкинге|библиотеке|музее)\s+[^\n.,!;]+)", re.IGNORECASE),
    re.compile(r"\b(на\s+(?:Невском|[А-ЯЁ][а-яё]+(?:ом|ой|ем)\s+(?:проспекте|улице))[^\n.,!;]*)", re.IGNORECASE),
]


def _to_number(raw: str) -> float | None:
    cleaned = re.sub(r"[\s ]", "", raw).replace(",", ".")
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


@app.post("/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest) -> ExtractResponse:
    if not req.raw_text or not req.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text is empty")
    try:
        text = req.raw_text
        return ExtractResponse(
            title=parse_title(text),
            date=parse_date(text),
            location=parse_location(text),
            price=parse_price(text),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to parse announcement text: {exc}")


@app.get("/register")
def register() -> dict:
    return {"status": "ok", "message": "TODO: implement registration"}


@app.post("/register")
def register_post(req: RegisterRequest) -> dict:
    # TODO: implement registration (DB in the next step)
    return {"status": "ok", "message": "TODO: implement registration"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "extractor"}
