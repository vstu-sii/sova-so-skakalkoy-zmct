"""Live smoke test from inside extractor; use a fresh demo token and empty budget."""
import argparse
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(token):
    text = "Встреча 20 ноября 2026 года в 18:00. Адрес: Москва, улица Мира, 5. Бесплатно."
    req = Request("http://127.0.0.1:8000/extract",
        data=json.dumps({"raw_text": text}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=195) as response:
            return response.status, response.headers
    except HTTPError as exc:
        return exc.code, exc.headers


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--standard", type=int, default=2)
    parser.add_argument("--economy", type=int, default=1)
    args = parser.parse_args()
    token = os.environ["EXTRACTOR_DEMO_TOKEN"]
    if not token:
        raise SystemExit("Set EXTRACTOR_DEMO_TOKEN before recreating extractor")
    assert request("invalid-demo-token")[0] == 401
    for tier in ["standard"] * args.standard + ["economy"] * args.economy:
        status, headers = request(token)
        source = headers.get("X-Extraction-Source")
        print(status, headers.get("X-Model-Tier"), source,
              "trace_id=" + str(headers.get("X-Trace-ID")), flush=True)
        if status != 200 or headers.get("X-Model-Tier") != tier or source != "ollama":
            raise SystemExit("Unexpected tier or regex fallback; inspect extractor and Ollama logs")
    status, headers = request(token)
    print(status, "retry_after=" + str(headers.get("Retry-After")), flush=True)
    if status != 429 or not headers.get("Retry-After"):
        raise SystemExit("Expected exhausted budget")
