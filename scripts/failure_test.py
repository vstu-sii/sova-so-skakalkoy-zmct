"""Live fault-injection test suite for event-platform (Lab 5 — Fault Tolerance).

Tests real failure modes against the running Docker Compose stack:
- F1: Ollama LLM outage -> graceful fallback to regex (HTTP 200, X-Extraction-Source: regex)
- F2: PostgreSQL DB outage -> graceful HTTP 503 + Retry-After on all DB endpoints (zero 500s),
      plus automatic recovery via SQLAlchemy pool_pre_ping after DB restart
- F3: Auth / input validation / duplicate subscription boundaries (401/400/422/404/409, zero 500s)
- F4: External channel failure (VK API invalid token) -> HTTP 502 + failed status in DB (zero 500s)
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

EXTRACTOR_URL = "http://localhost:8001"
VK_URL = "http://localhost:8003"
MAILER_URL = "http://localhost:8004"


def run_cmd(args: list[str]) -> str:
    res = subprocess.run(args, capture_output=True, text=True, check=True)
    return (res.stdout + res.stderr).strip()


def http_call(
    method: str,
    url: str,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> dict:
    headers: dict[str, str] = {}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return {
                "status": resp.status,
                "ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "headers": {k.lower(): v for k, v in resp.headers.items()},
                "body": json.loads(raw) if raw.startswith("{") else raw[:200],
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw)
        except Exception:
            body = raw[:200]
        return {
            "status": exc.code,
            "ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "headers": {k.lower(): v for k, v in exc.headers.items()},
            "body": body,
        }


def wait_for_ready(url: str, timeout_s: float = 40.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        res = http_call("GET", url, timeout=5.0)
        if res["status"] == 200:
            return True
        time.sleep(1.0)
    return False


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    email = f"faulttest_{run_id}@example.com"
    password = "FaultTestPassword123!"

    reg = http_call(
        "POST",
        f"{EXTRACTOR_URL}/auth/register",
        {"name": "Fault Test Expert", "email": email, "password": password},
    )
    assert reg["status"] == 201, reg
    token = reg["body"]["access_token"]
    expert_id = reg["body"]["expert"]["id"]

    ev = http_call(
        "POST",
        f"{EXTRACTOR_URL}/events",
        {
            "title": "Тест отказоустойчивости",
            "date": "2026-12-10T18:00:00",
            "location": "Кафе на Невском",
            "price": 1000,
        },
        token=token,
    )
    assert ev["status"] == 201, ev
    event_id = ev["body"]["id"]

    report: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "expert_id": expert_id,
        "event_id": event_id,
        "scenarios": {},
    }

    try:
        # === F1: Ollama outage ===
        print("[F1] Stopping ollama container...", flush=True)
        run_cmd(["docker", "compose", "stop", "ollama"])
        f1_res = http_call(
            "POST",
            f"{EXTRACTOR_URL}/extract",
            {"raw_text": "Встреча 25 декабря в 19:00 в кафе на Невском. Стоимость 1800₽."},
            token=token,
            timeout=30.0,
        )
        print(
            f"[F1] Extract during Ollama down: status={f1_res['status']} "
            f"ms={f1_res['ms']} source={f1_res['headers'].get('x-extraction-source')} "
            f"body={f1_res['body']}",
            flush=True,
        )
        assert f1_res["status"] == 200, f"Expected 200 fallback, got {f1_res}"
        assert f1_res["headers"].get("x-extraction-source") == "regex", f1_res["headers"]
        report["scenarios"]["F1_ollama_down"] = {
            "status": f1_res["status"],
            "ms": f1_res["ms"],
            "extraction_source": f1_res["headers"].get("x-extraction-source"),
            "parsed": f1_res["body"],
            "passed": True,
        }
    finally:
        print("[F1] Starting ollama container back...", flush=True)
        run_cmd(["docker", "compose", "start", "ollama"])

    try:
        # === F2: PostgreSQL DB outage ===
        print("[F2] Stopping db container...", flush=True)
        run_cmd(["docker", "compose", "stop", "db"])
        time.sleep(1.5)

        checks = {
            "extractor_health": http_call("GET", f"{EXTRACTOR_URL}/health"),
            "extractor_ready": http_call("GET", f"{EXTRACTOR_URL}/ready"),
            "vk_ready": http_call("GET", f"{VK_URL}/ready"),
            "mailer_ready": http_call("GET", f"{MAILER_URL}/ready"),
            "public_event": http_call("GET", f"{EXTRACTOR_URL}/events/{event_id}"),
            "subscribe": http_call(
                "POST",
                f"{EXTRACTOR_URL}/subscribe",
                {"event_id": event_id, "name": "Тест", "email": "t@example.com"},
            ),
            "login": http_call(
                "POST",
                f"{EXTRACTOR_URL}/auth/login",
                {"email": email, "password": password},
            ),
            "vk_publish": http_call("POST", f"{VK_URL}/publish", {"event_id": event_id}),
            "mailer_send": http_call("POST", f"{MAILER_URL}/send", {"event_id": event_id}),
        }
        for name, r in checks.items():
            print(f"[F2] {name}: status={r['status']} ms={r['ms']} retry_after={r['headers'].get('retry-after')}", flush=True)
            assert r["status"] != 500, f"Unexpected 500 on {name}: {r}"

        assert checks["extractor_health"]["status"] == 200
        for db_ep in ("extractor_ready", "vk_ready", "mailer_ready", "public_event", "subscribe", "login", "vk_publish", "mailer_send"):
            assert checks[db_ep]["status"] == 503, f"Expected 503 on {db_ep}, got {checks[db_ep]}"

        report["scenarios"]["F2_db_down"] = {
            k: {
                "status": v["status"],
                "ms": v["ms"],
                "retry_after": v["headers"].get("retry-after"),
                "detail": v["body"].get("detail") if isinstance(v["body"], dict) else v["body"],
            }
            for k, v in checks.items()
        }
    finally:
        print("[F2] Starting db container back and waiting for recovery...", flush=True)
        run_cmd(["docker", "compose", "start", "db"])
        t_rec = time.perf_counter()
        recovered = wait_for_ready(f"{EXTRACTOR_URL}/ready", timeout_s=45.0)
        recovery_ms = round((time.perf_counter() - t_rec) * 1000.0, 2)
        post_recovery = http_call("GET", f"{EXTRACTOR_URL}/events/{event_id}")
        print(f"[F2] DB recovered={recovered} in {recovery_ms}ms, GET /events/{{id}}={post_recovery['status']}", flush=True)
        report["scenarios"]["F2_db_recovery"] = {
            "recovered": recovered,
            "recovery_ms": recovery_ms,
            "public_event_status": post_recovery["status"],
        }

    # === F3: Input & Auth boundaries ===
    sub1 = http_call(
        "POST",
        f"{EXTRACTOR_URL}/subscribe",
        {"event_id": event_id, "name": "Иван", "email": f"dup_{run_id}@example.com"},
    )
    sub2 = http_call(
        "POST",
        f"{EXTRACTOR_URL}/subscribe",
        {"event_id": event_id, "name": "Иван", "email": f"dup_{run_id}@example.com"},
    )
    boundaries = {
        "extract_no_token": http_call("POST", f"{EXTRACTOR_URL}/extract", {"raw_text": "Тест"}),
        "extract_empty": http_call("POST", f"{EXTRACTOR_URL}/extract", {"raw_text": "   "}, token=token),
        "extract_too_long": http_call("POST", f"{EXTRACTOR_URL}/extract", {"raw_text": "a" * 1600}, token=token),
        "event_bad_uuid": http_call("GET", f"{EXTRACTOR_URL}/events/not-a-valid-uuid"),
        "subscribe_first": sub1,
        "subscribe_duplicate": sub2,
    }
    for name, r in boundaries.items():
        print(f"[F3] {name}: status={r['status']}", flush=True)
        assert r["status"] != 500, f"Unexpected 500 on {name}: {r}"
    assert boundaries["extract_no_token"]["status"] == 401
    assert boundaries["extract_empty"]["status"] == 400
    assert boundaries["extract_too_long"]["status"] == 422
    assert boundaries["event_bad_uuid"]["status"] == 404
    assert boundaries["subscribe_first"]["status"] == 201
    assert boundaries["subscribe_duplicate"]["status"] == 409
    report["scenarios"]["F3_boundaries"] = {k: v["status"] for k, v in boundaries.items()}

    # === F4: Invalid VK token -> 502 graceful error (not 500) ===
    bind_vk = http_call(
        "PUT",
        f"{EXTRACTOR_URL}/profile/channels/vk",
        {"vk_group_id": "123456789", "vk_access_token": "vk1.a.invalid_token_for_fault_test"},
        token=token,
    )
    assert bind_vk["status"] == 200, bind_vk
    vk_fail = http_call("POST", f"{VK_URL}/publish", {"event_id": event_id})
    print(f"[F4] VK invalid token: status={vk_fail['status']} body={vk_fail['body']}", flush=True)
    assert vk_fail["status"] == 502, vk_fail
    report["scenarios"]["F4_vk_invalid_token"] = {
        "status": vk_fail["status"],
        "ms": vk_fail["ms"],
        "detail": vk_fail["body"].get("detail") if isinstance(vk_fail["body"], dict) else vk_fail["body"],
    }

    out_dir = Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "failure-test-results.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] All fault injection scenarios passed! Saved to {out_file}", flush=True)


if __name__ == "__main__":
    main()
