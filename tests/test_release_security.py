"""Demo Day perimeter attacks. No external VK/SMTP targets are contacted."""
import importlib.util
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
OWNER = str(uuid.UUID(int=101))
OTHER = str(uuid.UUID(int=102))
EVENT = str(uuid.UUID(int=201))
SECRET = "synthetic-release-security-key-not-for-production"


@pytest.fixture(params=[("vk-publisher", "/publish"), ("mailer", "/send")])
def channel(request, monkeypatch):
    name, route = request.param
    folder = ROOT / "services" / name
    spec = importlib.util.spec_from_file_location(name + "_security", folder / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    monkeypatch.setenv("JWT_SECRET", SECRET)
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {"expert_id": OWNER}
    module.app.dependency_overrides[module.get_db] = lambda: db
    with TestClient(module.app) as client:
        yield module, route, client, db
    module.app.dependency_overrides.clear()


def token(owner=OWNER, secret=SECRET, expires=None):
    return jwt.encode({"sub": owner, "exp": expires or int(time.time())+60}, secret, algorithm="HS256")


@pytest.mark.parametrize("case", ["missing", "forged", "expired", "no_approve", "string_approve", "other_owner"])
def test_demo_day_dispatch_denied(channel, case):
    module, route, client, db = channel
    payload = {"event_id": EVENT, "approved": True}
    headers = {"Authorization": "Bearer " + token()}
    expected = {"missing": 401, "forged": 401, "expired": 401,
                "no_approve": 409, "string_approve": 422, "other_owner": 404}[case]
    if case == "missing":
        headers = {"X-User-Id": OWNER}
    elif case == "forged":
        headers["Authorization"] = "Bearer " + token(secret="attacker-controlled-test-key")
    elif case == "expired":
        headers["Authorization"] = "Bearer " + token(expires=int(time.time())-60)
    elif case == "no_approve":
        payload.pop("approved")
    elif case == "string_approve":
        payload["approved"] = "false"
    elif case == "other_owner":
        headers["Authorization"] = "Bearer " + token(owner=OTHER)
    response = client.post(route, json=payload, headers=headers)
    assert response.status_code == expected, response.text
    db.commit.assert_not_called()
    if case == "other_owner":
        db.execute.assert_called_once()
    else:
        db.execute.assert_not_called()


def test_owner_and_approval_pass_only_guard(channel):
    module, _, _, db = channel
    owner = module.authorize(EVENT, True, "Bearer " + token(), db)
    assert owner == OWNER
    sql, values = db.execute.call_args.args
    assert "FOR UPDATE" in str(sql) and values == {"id": EVENT}
    db.commit.assert_not_called()


def test_demo_key_is_not_valid_publication_configuration(channel, monkeypatch):
    _, route, client, db = channel
    monkeypatch.setenv("JWT_SECRET", "event-platform-dev-jwt-secret-change-me")
    response = client.post(route, json={"event_id": EVENT, "approved": True},
                           headers={"Authorization": "Bearer " + token()})
    assert response.status_code == 503
    db.execute.assert_not_called()
