"""Lab 5: real Delivery payload, fixed reference dates, per-request artifacts."""
import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from ml.dataset import load_dataset, expected_projection, model_input
from tests.evals.metrics import calculate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services/extractor/llm_logic.py"
spec = importlib.util.spec_from_file_location("delivery_llm_logic", SOURCE)
logic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logic)
COMMON = {"title", "date_start", "time_start", "venue", "price"}
VARIANTS = {
    "delivery_before": (False, False, False),
    "final": (True, True, True),
    "no_prompt": (False, True, True),
    "no_calendar": (True, False, True),
    "no_guards": (True, True, False),
}


def projected_event(result):
    value = result["date"]
    return dict(title=result["title"], date_start=value[:10] if value else None,
                time_start=value[11:16] if value and "T" in value else None,
                venue=result["location"], price=result["price"])


def projection(row):
    expected, fields = expected_projection(row)
    fields = [field for field in fields if field in COMMON]
    return {field: expected[field] for field in fields}, fields


def historical_common(rows):
    output = []
    for row in rows:
        fields = [f for f in row["assert_fields"] if f in COMMON]
        output.append(row | {"assert_fields": fields, "expected": {
            f: row["expected"][f] for f in fields}})
    return output


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def one(http, row, variant, model):
    text_input = model_input(row)
    text, reference = text_input["text"], text_input["reference_date"]
    expected, fields = projection(row)
    flags = VARIANTS[variant]
    payload = logic.payload(text, reference, model, prompt_v3=flags[0], calendar=flags[1])
    result = dict(id=row["id"], repeat=0, variant=variant, model=model,
                  expected=expected, assert_fields=fields, tags=row.get("tags", []),
                  attack=row.get("attack"), status="error", split=row.get("split"),
                  input_chars=len(text), over_delivery_input_limit=len(text) > 1500,
                  usage_complete=False)
    started = time.perf_counter()
    try:
        response = await http.post("/api/chat", json=payload)
        response.raise_for_status()
        envelope = response.json()
        counts = [envelope.get("prompt_eval_count"), envelope.get("eval_count")]
        if all(type(value) is int and value >= 0 for value in counts):
            result["usage"] = dict(input_tokens=counts[0], output_tokens=counts[1],
                                   cost_rub=0, cost_usd=0, attempts=1, cache_hit=False)
            result["usage_complete"] = True
        result["done_reason"] = envelope.get("done_reason")
        result["raw_response"] = envelope["message"]["content"]
        if envelope.get("done_reason") != "stop" or envelope.get("done") is not True:
            raise ValueError("incomplete response")
        parsed = logic.LLMFields.model_validate_json(result["raw_response"]).model_dump()
        output = logic.finalize(parsed, text, reference, calendar=flags[1], guards=flags[2])
        result.update(status="ok", event=projected_event(output), delivery_output=output,
                      postprocessing_changes=[k for k in parsed if parsed[k] != output[k]])
    except Exception as exc:
        result.update(error_type=type(exc).__name__)
    result["latency_ms"] = (time.perf_counter() - started) * 1000
    return result


async def run(args):
    source = Path(args.dataset)
    all_rows = load_dataset(source)
    rows = [r for r in all_rows if args.split == "all" or r.get("split") == args.split]
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=base, timeout=180, trust_env=False) as http:
        runtime = (await http.get("/api/version")).json()
        models = (await http.get("/api/tags")).json()
        for variant in args.variants:
            out = output / variant
            out.mkdir(exist_ok=True)
            saved = {}
            raw = out / "requests.jsonl"
            if args.resume and raw.exists():
                for line in raw.read_text(encoding="utf-8").splitlines():
                    r = json.loads(line)
                    saved[r["id"]] = r
                metadata = json.loads((out / "run.json").read_text(encoding="utf-8"))
                required = dict(
                    source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    dataset_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    model=args.model, split=args.split, variant=variant,
                )
                if any(metadata.get(k) != value for k, value in required.items()):
                    raise ValueError("source/data/config changed; resume refused")
            metadata = dict(model=args.model, runtime=runtime, models=models,
                dataset_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                split=args.split, records=len(rows), variant=variant,
                flags=VARIANTS[variant], timestamp=datetime.now(timezone.utc).isoformat(),
                python=platform.python_version(), host=platform.platform(),
                revision=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
                scope="Delivery extraction kernel, no auth/DB/HTTP-app overhead, no fallback",
                rag=False, keep_alive=0, num_ctx=2048, num_predict=256)
            dump(out / "run.json", metadata)
            with raw.open("a" if args.resume else "w", encoding="utf-8") as stream:
                if not args.resume:
                    saved = {}
                for row in rows:
                    if row["id"] in saved:
                        continue
                    result = await one(http, row, variant, args.model)
                    stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                    stream.flush()
                    saved[row["id"]] = result
                    print(variant, row["id"], result["status"], round(result["latency_ms"]), flush=True)
            observed = [saved[r["id"]] for r in rows]
            dump(out / "metrics.json", calculate(observed))
            with (out / "usage.csv").open("w", newline="", encoding="utf-8") as stream:
                names = ["id", "status", "latency_ms", "input_tokens", "output_tokens", "usage_complete"]
                writer = csv.DictWriter(stream, fieldnames=names)
                writer.writeheader()
                for r in observed:
                    writer.writerow({k: r.get(k, (r.get("usage") or {}).get(k)) for k in names})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", default="docs/quality/golden-dataset/v3.jsonl")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--model", default="qwen2.5:1.5b")
    p.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    p.add_argument("--output", default="docs/experiments/lab5-dev")
    p.add_argument("--resume", action="store_true")
    asyncio.run(run(p.parse_args()))
