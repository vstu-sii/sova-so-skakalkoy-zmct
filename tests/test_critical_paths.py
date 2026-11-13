"""Critical API and output-boundary checks with inert local fixtures."""
import copy
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.main import app
from ml.models.baseline import ModelError, zero_usage
from tests.evals.quality_gate import aggregate, write_rows
from tests.test_api import BODY, HEADERS, client
from tests.test_baseline import EVENT

REPLAY_PATH = Path(__file__).resolve().parents[1] / "docs/quality/reports/lab4-security-model/requests.jsonl"
REPLAY_ROWS = [json.loads(line) for line in REPLAY_PATH.read_text(encoding="utf-8").splitlines()]
REPLAY_BLOCKED = {"gd-0010", "gd-0037", "gd-0042"}


def counts():
    with closing(sqlite3.connect(os.environ["AI_DB_PATH"])) as db:
        return tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("events", "idem"))


@pytest.fixture
def before_or_after(monkeypatch):
    before = os.getenv("LAB4_REPLAY_BEFORE") == "1"
    if before:
        # Test-only control, never an application configuration switch.
        monkeypatch.setattr("backend.routers.ai.enforce_output_policy", lambda _: None)
    return before


@pytest.mark.parametrize(("field", "sample"), [
    ("registration", "https://quality-check.invalid/direct"),
    ("description", "https://quality-check.invalid/quoted"),
    ("venue", "www.quality-check.invalid"),
    ("description", "<span>synthetic fixture</span>"),
])
def test_quarantine_output(client, before_or_after, field, sample):
    event = copy.deepcopy(EVENT) | {field: sample}
    app.state.model.extract = AsyncMock(return_value=dict(event=event, issues=[], usage=zero_usage()))
    response = client.post("/v1/ai/extractions", json=BODY, headers=HEADERS)
    if before_or_after:
        assert response.status_code == 200
        assert sample in response.text
    else:
        assert response.status_code == 422
        assert "quality-check.invalid" not in response.text
        assert "synthetic fixture" not in response.text
        assert counts() == (0, 0)


@pytest.mark.parametrize("row", REPLAY_ROWS, ids=[r["id"] for r in REPLAY_ROWS])
def test_replay_same_model_output(client, before_or_after, row):
    """Keep provider output fixed to isolate the API boundary change."""
    result = {field: row[field] for field in ("event", "issues", "usage")}
    app.state.model.extract = AsyncMock(return_value=copy.deepcopy(result))
    response = client.post("/v1/ai/extractions", json=BODY, headers=HEADERS)
    blocked = not before_or_after and row["id"] in REPLAY_BLOCKED
    assert response.status_code == (422 if blocked else 200)
    assert counts() == ((0, 0) if blocked else (1, 1))


def test_limit_is_checked_before_inference(client):
    response = client.post("/v1/ai/extractions", json=BODY | {"text": "x" * 12001}, headers=HEADERS)
    assert response.status_code == 422
    response = client.post("/v1/ai/extractions", json=BODY | {"text": "x" * 100001}, headers=HEADERS)
    assert response.status_code == 413
    assert app.state.model.calls == 0


@pytest.mark.parametrize("failure", [TimeoutError(), ModelError("MODEL_UNAVAILABLE", True)])
def test_degraded_model_retry_leaves_no_partial_write(client, failure):
    app.state.model.extract = AsyncMock(side_effect=[
        failure, dict(event=copy.deepcopy(EVENT), issues=[], usage=zero_usage())
    ])
    failed = client.post("/v1/ai/extractions", json=BODY, headers=HEADERS)
    assert failed.status_code == 503
    assert failed.json()["retryable"] is True
    assert counts() == (0, 0)
    assert client.post("/v1/ai/extractions", json=BODY, headers=HEADERS).status_code == 200


def test_confirm_then_generate_blocks_unreviewed_draft(client, before_or_after):
    extracted = client.post("/v1/ai/extractions", json=BODY, headers=HEADERS).json()
    path = "/v1/events/" + extracted["event_id"]
    sample = "https://quality-check.invalid/draft"
    generation = AsyncMock(return_value=dict(
        contents=[dict(platform="site", markdown=sample)], issues=[],
        usage=zero_usage(), mode="template",
    ))
    app.state.model.generate = generation
    payload = dict(expected_version=1, platforms=["site"], tone="", preferred_mode="economy")
    assert client.post(path + "/ai/generations", json=payload, headers=HEADERS).status_code == 422
    generation.assert_not_awaited()
    confirm = dict(candidate_id=extracted["candidate"]["candidate_id"], expected_version=1)
    assert client.post(path + "/confirm", json=confirm, headers=HEADERS).status_code == 200
    response = client.post(path + "/ai/generations", json=payload | {"expected_version": 2}, headers=HEADERS)
    assert response.status_code == (200 if before_or_after else 422)
    assert (sample in response.text) == before_or_after
    generation.assert_awaited_once()


def test_gate_rejects_missing_duplicate_and_changed_rows(tmp_path):
    row = dict(id="sample", expected={"title": "Лекция"}, assert_fields=["title"])
    result = dict(id="sample", repeat=0, expected=row["expected"], assert_fields=["title"],
                  tags=[], attack=None, model="qwen2.5:3b")
    file = tmp_path / "requests.jsonl"
    write_rows(file, [result])
    assert aggregate([row], [file], 1) == [result]
    with pytest.raises(ValueError, match="missing"):
        aggregate([row], [file], 2)
    with pytest.raises(ValueError, match="duplicate"):
        aggregate([row], [file, file], 1)
    write_rows(file, [result | {"expected": {"title": "Другой"}}])
    with pytest.raises(ValueError, match="reference data"):
        aggregate([row], [file], 1)
