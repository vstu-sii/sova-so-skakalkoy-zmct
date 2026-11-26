"""Application authorization and explicit approval before external side effects."""
import logging
import os
import uuid

import jwt
from fastapi import HTTPException
from sqlalchemy import text


def authorize(event_id, approved, authorization, db):
    secret = os.getenv("JWT_SECRET", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Требуется авторизация")
    if len(secret) < 32 or secret == "event-platform-dev-jwt-secret-change-me":
        raise HTTPException(503, "Настройте JWT_SECRET перед публикацией")
    try:
        claims = jwt.decode(authorization[7:], secret, algorithms=["HS256"],
                            options={"require": ["sub", "exp"]})
        owner = uuid.UUID(claims["sub"])
        event = uuid.UUID(event_id)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, "Недействительный токен") from None
    if approved is not True:
        raise HTTPException(409, "Требуется явное подтверждение отправки")
    # Hold the row lock through formatting/dispatch/commit in the same session.
    row = db.execute(text(
        "SELECT expert_id FROM events WHERE id = :id FOR UPDATE"
    ), {"id": str(event)}).mappings().first()
    if row is None or str(row["expert_id"]) != str(owner):
        logging.getLogger("uvicorn.error").warning("publication_denied reason=ownership")
        raise HTTPException(404, "Мероприятие не найдено")
    return str(owner)
