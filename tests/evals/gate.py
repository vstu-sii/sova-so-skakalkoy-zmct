"""Split the full corpus for CI and aggregate only complete, matching runs."""
import argparse
import hashlib
import json
from pathlib import Path

from ml.dataset import expected_projection, load_dataset
from tests.evals.metrics import calculate, check_gates


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def aggregate(dataset, inputs, repeats):
    expected = {(row["id"], n): row for row in dataset for n in range(repeats)}
    observed = {}
    for file in inputs:
        for line in file.read_text(encoding="utf-8").splitlines():
            result = json.loads(line)
            key = (result["id"], result["repeat"])
            if key not in expected or key in observed:
                raise ValueError(f"unexpected or duplicate result {key}")
            row = expected[key]
            values, fields = expected_projection(row)
            if any(result.get(k) != v for k, v in {
                "expected": values, "assert_fields": fields, "tags": row.get("tags", []),
                "attack": row.get("attack"), "model": "qwen2.5:3b",
            }.items()):
                raise ValueError(f"result does not match the reference data: {key}")
            observed[key] = result
    missing = expected.keys() - observed.keys()
    if missing:
        raise ValueError(f"missing {len(missing)} evaluations")
    return [observed[key] for key in sorted(observed)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("docs/quality/golden-dataset/v3.jsonl"))
    sub = parser.add_subparsers(dest="command", required=True)
    split = sub.add_parser("split")
    split.add_argument("--index", type=int, required=True)
    split.add_argument("--count", type=int, required=True)
    split.add_argument("--output", type=Path, required=True)
    security = sub.add_parser("security-subset")
    security.add_argument("--output", type=Path, required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--results", type=Path, required=True)
    merge.add_argument("--thresholds", type=Path, required=True)
    merge.add_argument("--repeats", type=int, default=1)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = load_dataset(args.dataset)
    if args.command == "security-subset":
        cases = [row for row in rows if row.get("attack")]
        if not cases:
            parser.error("no security cases")
        write_rows(args.output, cases)
        return
    if args.command == "split":
        if not 0 <= args.index < args.count <= len(rows):
            parser.error("invalid shard configuration")
        write_rows(args.output, rows[args.index::args.count])
        return

    report = {"dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
              "dataset_records": len(rows), "repeats": args.repeats}
    try:
        observed = aggregate(rows, sorted(args.results.rglob("requests.jsonl")), args.repeats)
        report["observations"] = len(observed)
        report["metrics"] = calculate(observed)
        report["gate_errors"] = check_gates(
            report["metrics"], json.loads(args.thresholds.read_text(encoding="utf-8"))
        )
    except (ValueError, KeyError, OSError) as exc:
        report["gate_errors"] = [str(exc)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report["gate_errors"]))


if __name__ == "__main__":
    main()
