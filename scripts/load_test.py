"""Reproducible load test for event-platform MVP across UC-01 and UC-04 profiles.

Measures throughput (RPS), latency percentiles (p50, p95, p99, max), and error rates
across escalating concurrency levels, plus a dedicated AI extraction benchmark.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sys
import time
import urllib.error
import urllib.request
import uuid

EXTRACTOR_URL = "http://localhost:8001"
COMPOSER_URL = "http://localhost:8002"
VK_URL = "http://localhost:8003"
SITE_URL = "http://localhost:8010"


@dataclass
class StepStats:
    scenario: str
    concurrency: int
    total_requests: int
    duration_s: float
    rps: float
    ok_count: int
    error_count: int
    status_counts: dict[str, int]
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    mean_ms: float


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 2)


def http_call(
    method: str,
    url: str,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, float, dict | str]:
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
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            try:
                body: dict | str = json.loads(raw)
            except Exception:
                body = raw[:200]
            return resp.status, elapsed_ms, body
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        raw = exc.read().decode("utf-8", errors="ignore")
        return exc.code, elapsed_ms, raw[:200]
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return 0, elapsed_ms, f"{type(exc).__name__}: {exc}"


def run_stage(
    scenario_name: str,
    concurrency: int,
    total_requests: int,
    worker_fn,
) -> StepStats:
    latencies: list[float] = []
    status_counts: dict[str, int] = {}
    ok_count = 0
    error_count = 0

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker_fn, i) for i in range(total_requests)]
        for fut in as_completed(futures):
            code, ms = fut.result()
            latencies.append(ms)
            key = str(code)
            status_counts[key] = status_counts.get(key, 0) + 1
            if 200 <= code < 400:
                ok_count += 1
            else:
                error_count += 1
    duration_s = max(0.001, time.perf_counter() - t_start)

    return StepStats(
        scenario=scenario_name,
        concurrency=concurrency,
        total_requests=total_requests,
        duration_s=round(duration_s, 3),
        rps=round(total_requests / duration_s, 2),
        ok_count=ok_count,
        error_count=error_count,
        status_counts=status_counts,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        max_ms=round(max(latencies), 2) if latencies else 0.0,
        mean_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
    )


def main() -> None:
    run_id = uuid.uuid4().hex[:8]
    email = f"loadtest_{run_id}@example.com"
    password = "LoadTestPassword123!"

    print(f"[setup] Registering load-test expert {email}...", flush=True)
    code, _, body = http_call(
        "POST",
        f"{EXTRACTOR_URL}/auth/register",
        {"name": "Load Test Expert", "email": email, "password": password},
    )
    assert code == 201 and isinstance(body, dict), f"Register failed: {code} {body}"
    token = body["access_token"]
    expert_id = body["expert"]["id"]

    code, _, ev_body = http_call(
        "POST",
        f"{EXTRACTOR_URL}/events",
        {
            "title": "Нагрузочный тест: Мастер-класс по архитектуре",
            "date": "2026-12-05T19:00:00",
            "location": "Лофт на Невском, 28",
            "price": 1500,
            "description": "Тестовое мероприятие для нагрузочного прогона Demo Day.",
        },
        token=token,
    )
    assert code == 201 and isinstance(ev_body, dict), f"Create event failed: {code} {ev_body}"
    event_id = ev_body["id"]
    print(f"[setup] Created event_id={event_id}", flush=True)

    # Mixed UC profile:
    # 70% UC-04 public event read (GET /events/{id})
    # 15% UC-04 visitor subscription (POST /subscribe)
    # 10% UC-01 dashboard listing (GET /events)
    #  5% UC-04 page-composer (POST /compose)
    def mixed_uc_worker(idx: int) -> tuple[int, float]:
        r = idx % 20
        if r < 14:  # 70%
            c, ms, _ = http_call("GET", f"{EXTRACTOR_URL}/events/{event_id}")
            return c, ms
        if r < 17:  # 15%
            c, ms, _ = http_call(
                "POST",
                f"{EXTRACTOR_URL}/subscribe",
                {
                    "event_id": event_id,
                    "name": f"Участник {idx}",
                    "email": f"sub_{run_id}_{idx}_{uuid.uuid4().hex[:6]}@example.com",
                },
            )
            return c, ms
        if r < 19:  # 10%
            c, ms, _ = http_call("GET", f"{EXTRACTOR_URL}/events", token=token)
            return c, ms
        c, ms, _ = http_call("POST", f"{COMPOSER_URL}/compose", {"event_id": event_id})
        return c, ms

    def frontend_ssr_worker(_idx: int) -> tuple[int, float]:
        c, ms, _ = http_call("GET", f"{SITE_URL}/event/{event_id}")
        return c, ms

    def vk_publish_worker(_idx: int) -> tuple[int, float]:
        c, ms, _ = http_call("POST", f"{VK_URL}/publish", {"event_id": event_id})
        return c, ms

    results: list[StepStats] = []

    stages = [
        ("mixed_uc_c5", 5, 100, mixed_uc_worker),
        ("mixed_uc_c20", 20, 300, mixed_uc_worker),
        ("mixed_uc_c50", 50, 500, mixed_uc_worker),
        ("mixed_uc_c100", 100, 600, mixed_uc_worker),
        ("frontend_ssr_c20", 20, 100, frontend_ssr_worker),
        ("vk_publish_mock_c10", 10, 40, vk_publish_worker),
    ]

    for name, conc, count, fn in stages:
        print(f"[run] {name} (concurrency={conc}, requests={count})...", flush=True)
        stats = run_stage(name, conc, count, fn)
        results.append(stats)
        print(
            f"      RPS={stats.rps} ok={stats.ok_count}/{stats.total_requests} "
            f"p50={stats.p50_ms}ms p95={stats.p95_ms}ms p99={stats.p99_ms}ms "
            f"max={stats.max_ms}ms statuses={stats.status_counts}",
            flush=True,
        )

    # Dedicated UC-01 AI Extraction benchmark (Ollama qwen2.5:1.5b serialized by llm_lock)
    print("[run] ai_extract_sequential (concurrency=1, requests=3)...", flush=True)
    ai_sources: list[str] = []

    def ai_extract_worker(idx: int) -> tuple[int, float]:
        sample = (
            f"Воркшоп #{idx + 1} по продуктовой аналитике 18 декабря в 19:00. "
            "Адрес: Москва, ул. Покровка, 14. Стоимость 2500 рублей."
        )
        req = urllib.request.Request(
            f"{EXTRACTOR_URL}/extract",
            data=json.dumps({"raw_text": sample}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=180.0) as resp:
                src = resp.headers.get("X-Extraction-Source", "unknown")
                ai_sources.append(src)
                resp.read()
                return resp.status, (time.perf_counter() - t0) * 1000.0
        except urllib.error.HTTPError as exc:
            exc.read()
            return exc.code, (time.perf_counter() - t0) * 1000.0
        except Exception:
            return 0, (time.perf_counter() - t0) * 1000.0

    ai_seq = run_stage("ai_extract_c1", 1, 3, ai_extract_worker)
    results.append(ai_seq)
    print(
        f"      RPS={ai_seq.rps} ok={ai_seq.ok_count}/{ai_seq.total_requests} "
        f"p50={ai_seq.p50_ms}ms p95={ai_seq.p95_ms}ms max={ai_seq.max_ms}ms sources={ai_sources}",
        flush=True,
    )

    ai_conc = run_stage("ai_extract_c3", 3, 3, ai_extract_worker)
    results.append(ai_conc)
    print(
        f"[run] ai_extract_c3: RPS={ai_conc.rps} ok={ai_conc.ok_count}/{ai_conc.total_requests} "
        f"p50={ai_conc.p50_ms}ms p95={ai_conc.p95_ms}ms max={ai_conc.max_ms}ms",
        flush=True,
    )

    out_dir = Path("docs/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "load-test-results.json"
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "expert_id": expert_id,
        "event_id": event_id,
        "ai_extraction_sources": ai_sources,
        "stages": [s.__dict__ for s in results],
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] Saved results to {out_file}", flush=True)


if __name__ == "__main__":
    main()
