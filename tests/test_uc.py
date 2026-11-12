"""Traceable critical UC checks using real HTTP handlers and local SQLite."""
import importlib.util
import json
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from ml.models.baseline import Baseline, zero_usage
from tests.test_api import BODY, HEADERS, client
from tests.test_baseline import EVENT

ROOT = Path(__file__).resolve().parents[1]


def load_service(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "services" / name / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post(client, path, payload, key, code=200):
    response = client.post(path, json=payload, headers=HEADERS | {"Idempotency-Key": key})
    assert response.status_code == code, response.text
    return response.json()


def extract(client):
    result = post(client, "/v1/ai/extractions", BODY, "uc-extract")
    return "/v1/events/" + result["event_id"], result["candidate"]


def confirm(client, path, candidate, version, key="uc-confirm"):
    return post(client, path + "/confirm", dict(
        candidate_id=candidate["candidate_id"], expected_version=version), key)


def use_baseline(event):
    model = Baseline()
    usage = zero_usage()
    model._request = AsyncMock(return_value=(json.dumps(dict(event=event, issues=[])), usage))
    app.state.model = model
    return model


def test_uc01_extract_confirm_compose_three_drafts(client, monkeypatch):
    model = use_baseline(EVENT)
    path, candidate = extract(client)
    confirmed = confirm(client, path, candidate, 1)
    assert confirmed["event"] == EVENT
    generation = post(client, path + "/ai/generations", dict(
        expected_version=2, platforms=["vk", "email", "site"], tone="",
        preferred_mode="economy"), "uc-generate")
    assert generation["status"] == "draft_content"
    drafts = {row["platform"]: row for row in generation["contents"]}
    assert set(drafts) == {"vk", "email", "site"}
    assert drafts["vk"]["headline"] == EVENT["title"]
    assert drafts["email"]["subject"] == EVENT["title"]
    assert EVENT["title"] in drafts["site"]["markdown"]
    assert all("1000 RUB" in drafts[key][field] for key, field in [
        ("vk", "body"), ("email", "body"), ("site", "markdown")
    ])
    model._request.assert_awaited_once()

    # Test transport connects the existing composer loader to the confirmed card.
    composer = load_service("page-composer")
    def load_confirmed(event_id):
        assert event_id == path.rsplit("/", 1)[1]
        card = client.get(path, headers=HEADERS).json()["event"]
        return card | {"location": card["venue"]}
    monkeypatch.setattr(composer, "load_event", load_confirmed)
    with TestClient(composer.app) as page:
        response = page.post("/compose", json={"event_id": path.rsplit("/", 1)[1]})
    assert response.status_code == 200
    blocks = {block["type"]: block["data"] for block in response.json()["blocks"]}
    assert blocks["hero"]["title"] == EVENT["title"]
    assert blocks["pricing"]["price"] == EVENT["price"]
    assert blocks["location"]["location"] == EVENT["venue"]


def test_uc07_carousel_order_limit_and_duplicates():
    composer = load_service("page-composer")
    media = [f"image-{i}" for i in range(composer.MAX_CAROUSEL_ITEMS)]
    with TestClient(composer.app) as client:
        response = client.post("/compose", json={"event_id": "demo", "media": media})
        assert response.status_code == 200
        assert response.json()["blocks"][-1]["data"]["media"] == media
        for invalid in (media + ["extra"], ["same", "same"]):
            assert client.post("/compose", json={"event_id": "demo", "media": invalid}).status_code == 422


def test_uc08_reschedule_confirmed_event_keeps_old_version_until_approve(client):
    model = use_baseline(EVENT)
    path, candidate = extract(client)
    confirm(client, path, candidate, 1)
    text = "Перенести на 21 ноября 2026"
    model._request.return_value = (json.dumps(dict(changes=[
        dict(field="date_start", operation="set", value="2026-11-21", evidence=text)
    ], issues=[])), zero_usage())
    patch = post(client, path + "/ai/patches", BODY | {
        "text": text, "expected_version": 2
    }, "uc-patch")
    assert client.get(path, headers=HEADERS).json()["event"]["date_start"] == EVENT["date_start"]
    updated = confirm(client, path, patch["candidate"], 2, "uc-confirm-patch")
    assert updated["version"] == 3
    assert updated["event"] == EVENT | {"date_start": "2026-11-21"}


def test_uc09_unapproved_event_cannot_generate_or_publish(client):
    model = use_baseline(EVENT)
    path, _ = extract(client)
    post(client, path + "/ai/generations", dict(
        expected_version=1, platforms=["vk"], tone="", preferred_mode="economy"
    ), "uc-unapproved", code=422)
    model._request.assert_awaited_once()
    assert client.post(path + "/publish", json={}, headers=HEADERS).status_code == 404
    # Delivery stubs expose no dispatch capability.
    for name, route, body in [
        ("vk-publisher", "/publish", {"event_id": "draft"}),
        ("mailer", "/send", {"event_id": "draft", "recipients": []}),
    ]:
        with TestClient(load_service(name).app) as channel:
            assert channel.post(route, json=body).json()["status"] == "not_implemented"


def test_uc10_email_title_special_characters_stay_in_one_header(client):
    title = "Лекция «А & Б»\r\nДополнение: пример"
    use_baseline(EVENT | {"title": title})
    path, candidate = extract(client)
    confirm(client, path, candidate, 1)
    result = post(client, path + "/ai/generations", dict(
        expected_version=2, platforms=["email"], tone="", preferred_mode="economy"
    ), "uc-email")
    subject = result["contents"][0]["subject"]
    assert "«А & Б»" in subject
    assert "\r" not in subject and "\n" not in subject
    message = EmailMessage()
    message["Subject"] = subject
    assert list(message.keys()) == ["Subject"]
