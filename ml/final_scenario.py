"""Live /extract measurement, in-process ASGI transport and real local Ollama."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "services/extractor"))
    spec = importlib.util.spec_from_file_location("delivery_scenario", root / "services/extractor/main.py")
    delivery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(delivery)
    delivery.OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    delivery.app.dependency_overrides[delivery.get_db] = lambda: None
    out = root / "docs/experiments/lab5-run/scenario.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    token = "lab5-offline-measurement"
    results = []

    def count(direction):
        return delivery.TOKENS.labels("standard", direction)._value.get()

    with patch.object(delivery, "ensure_schema"), patch.object(
        delivery, "tokens_to_owner", {token: "lab5-synthetic-owner"}
    ), TestClient(delivery.app) as client:
        for version in ("delivery_before", "lab5-guarded"):
            with patch.dict(os.environ, {"AI_EXTRACTION_VERSION": version}):
                before_in, before_out = count("input"), count("output")
                started = time.perf_counter()
                response = client.post("/extract", headers={"Authorization": "Bearer " + token},
                    json={"raw_text": "Лекция «Границы». 20 декабря 2026 в 18:00. Адрес: Москва, Лесная 10. Бесплатно."})
                result = dict(version=version, status=response.status_code,
                    latency_ms=(time.perf_counter()-started)*1000,
                    input_tokens=count("input")-before_in, output_tokens=count("output")-before_out,
                    source=response.headers.get("X-Extraction-Source"),
                    tier=response.headers.get("X-Model-Tier"), response=response.json())
                results.append(result)
                if response.status_code != 200 or result["source"] != "ollama":
                    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                    raise SystemExit("Live extraction failed; see scenario.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
