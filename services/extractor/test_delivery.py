import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import main
from budget import DailyBudget
from telemetry import provider


class BudgetTest(unittest.TestCase):
    def test_owner_isolation_midnight_and_missing_usage(self):
        day = [date(2026, 11, 12)]
        budget = DailyBudget((1, 3000), (1, 3000), day=lambda: day[0])
        first, _ = budget.reserve("a", 2304)
        budget.settle(first, None)
        self.assertEqual(first.usage.tokens, 2304)
        self.assertEqual(budget.reserve("a", 2304)[0].tier, "economy")
        self.assertIsNone(budget.reserve("a", 2304)[0])
        self.assertEqual(budget.reserve("b", 2304)[0].tier, "standard")
        day[0] = date(2026, 11, 13)
        self.assertEqual(budget.reserve("a", 2304)[0].tier, "standard")

    def test_token_budget_can_degrade_before_request_limit(self):
        budget = DailyBudget((100, 2500), (20, 4000))
        reservation, _ = budget.reserve("a", 2304)
        budget.settle(reservation, 300)
        reservation, reason = budget.reserve("a", 2304)
        self.assertEqual((reservation.tier, reason), ("economy", "tokens"))

    def test_concurrent_reservation_does_not_overspend(self):
        budget = DailyBudget((5, 100), (2, 100))
        with ThreadPoolExecutor(max_workers=8) as pool:
            result = list(pool.map(lambda _: budget.reserve("a", 10)[0], range(40)))
        self.assertEqual(sum(r is not None for r in result), 7)


class ApiTest(unittest.TestCase):
    def test_auth_budget_traces_and_metrics_through_http(self):
        models = []
        seen_owner = []
        response_body = dict(title="Встреча", date=None, location=None, price=0)

        def ollama(request):
            payload = json.loads(request.content)
            models.append(payload["model"])
            self.assertNotIn("tools", payload)
            return httpx.Response(200, json=dict(
                done=True, done_reason="stop", prompt_eval_count=420, eval_count=25,
                message={"content": json.dumps(response_body)},
            ))

        def save(_db, _text, _parsed, owner):
            seen_owner.append(owner)
            return "demo-event"

        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(ollama)
        main.app.dependency_overrides[main.get_db] = lambda: None
        self.addCleanup(main.app.dependency_overrides.clear)
        with patch.object(main, "budget", DailyBudget((1, 10000), (1, 10000))), \
             patch.object(main, "tokens_to_owner", {"a-demo": "a", "b-demo": "b"}), \
             patch.object(main, "save_extracted_event", side_effect=save), \
             patch.object(main.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)), \
             TestClient(main.app) as client:
            body = {"raw_text": "Синтетический анонс"}
            self.assertEqual(client.post("/extract", json=body, headers={"X-User-Id": "a"}).status_code, 401)
            headers = {"Authorization": "Bearer a-demo"}
            first = client.post("/extract", json=body, headers=headers)
            second = client.post("/extract", json=body, headers=headers | {"X-User-Id": "b"})
            third = client.post("/extract", json=body, headers=headers)
            other = client.post("/extract", json=body, headers={"Authorization": "Bearer b-demo"})
            self.assertEqual([r.status_code for r in (first, second, third, other)], [200, 200, 429, 200])
            self.assertEqual(first.headers["X-Model-Tier"], "standard")
            self.assertEqual(second.headers["X-Model-Tier"], "economy")
            self.assertEqual(second.headers["X-Extraction-Source"], "ollama")
            self.assertTrue(third.headers["Retry-After"].isdigit())
            self.assertEqual(models, [main.MODELS["standard"], main.MODELS["economy"], main.MODELS["standard"]])
            self.assertEqual(seen_owner, ["a", "a", "b"])
            metrics = client.get("/metrics").text
            self.assertIn('extractor_llm_tokens_total{direction="input",tier="economy"} 420.0', metrics)
            self.assertIn('extractor_limit_decisions_total{decision="degraded",reason="requests"} 1.0', metrics)
        trace_id = int(second.headers["X-Trace-ID"], 16)
        spans = {s.name: s for s in exporter.get_finished_spans() if s.context.trace_id == trace_id}
        self.assertEqual(spans["ollama.chat"].parent.span_id, spans["POST /extract"].context.span_id)
        self.assertEqual(spans["ollama.chat"].attributes["gen_ai.usage.output_tokens"], 25)
        self.assertNotIn("Синтетический анонс", repr(spans["ollama.chat"].attributes))
