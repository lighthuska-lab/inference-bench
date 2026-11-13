"""Collect fresh streaming compatibility reports from an existing local server."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

from inference_bench.benchmark import BenchmarkConfig, run_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    # A fresh directory is mandatory, so previous evidence cannot be replaced.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[2] / "src" / "inference_bench"
    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(source.glob("*.py"))
        },
        "purpose": "loopback CPU compatibility, not a capacity or p99 comparison",
    }
    (args.output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2) + "\n"
    )
    for trial, concurrency in enumerate((1, 2, 2, 1), start=1):
        report = run_benchmark(
            BenchmarkConfig(
                base_url="http://127.0.0.1:18765/v1",
                model="smollm2-135m-q4-k-m",
                prompt=(
                    "List the integers from one through one hundred, "
                    "separated by commas."
                ),
                requests=4,
                concurrency=concurrency,
                warmup=1,
                max_completion_tokens=16,
                timeout_seconds=60,
                stream=True,
            )
        )
        name = f"trial-{trial}-c{concurrency}.json"
        (args.output_dir / name).write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
        summary = report["summary"]
        print(name, json.dumps(summary), flush=True)
        if report["warmup"]["failed_requests"] or summary["failed_requests"]:
            raise SystemExit("Compatibility run failed; partial evidence retained.")
        if summary["first_content_ms"]["samples"] != 4:
            raise SystemExit("Missing first-content measurements; evidence retained.")


if __name__ == "__main__":
    main()
