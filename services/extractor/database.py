import logging
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://event_platform:changeme@localhost:5432/event_platform"
)

DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "10"))

connect_args = {"connect_timeout": DB_CONNECT_TIMEOUT} if DATABASE_URL.startswith("postgresql") else {}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def check_db_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def ensure_schema() -> None:
    """Idempotently ensure incremental columns exist on already-initialized DB volumes."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE experts ALTER COLUMN avatar_url TYPE TEXT"
                )
            )
    except Exception as exc:
        logger.warning("ensure_schema skipped: %s", exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
