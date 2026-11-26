import logging
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("uvicorn.error")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://event_platform:changeme@localhost:5432/event_platform"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema() -> None:
    """Idempotently ensure incremental columns exist on already-initialized DB volumes."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)"
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
