"""Run regression in an isolated detached worktree of an existing release tag."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="v1.0.0-demo")
    parser.add_argument("--output", type=Path, default=Path("docs/quality/reports/lab5-release"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(["git", "rev-parse", f"refs/tags/{args.tag}^{{commit}}"],
                                     cwd=root, text=True).strip()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sova-release-") as temp:
        checkout = Path(temp) / "checkout"
        subprocess.run(["git", "worktree", "add", "--detach", str(checkout), commit], cwd=root, check=True)
        try:
            env = os.environ | {"LLM_PROVIDER": "ollama", "LLM_MODEL": "qwen2.5:3b",
                "AI_CALL_TIMEOUT": "120", "AI_DEADLINE": "245", "AI_TRACE_CONTENT": "false",
                "PYTHONIOENCODING": "utf-8"}
            verification = subprocess.run([sys.executable, "-m", "tests.evals.verify_model"],
                                           cwd=checkout, env=env)
            if verification.returncode:
                raise SystemExit(verification.returncode)
            command = [sys.executable, "-m", "tests.evals.run", "--dataset",
                "docs/quality/golden-dataset/v3.jsonl", "--split", "all", "--repeats", "1",
                "--gate", "tests/evals/quality-thresholds.json", "--output", str(out)]
            with (out / "console.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT)
            provenance = dict(tag=args.tag, commit=commit, exit_code=result.returncode,
                              command=command, scope="Exact code and dataset of release tag")
            (out / "release.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(checkout)], cwd=root, check=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
