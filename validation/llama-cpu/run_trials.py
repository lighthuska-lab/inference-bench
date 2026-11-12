"""Collect small real-model compatibility trials against a prestarted local server."""

from __future__ import annotations

import argparse
import json
import os
import platform
import urllib.request
from pathlib import Path

from inference_bench.benchmark import BenchmarkConfig, completion_url, run_benchmark

PROMPT = "List the integers from one through one hundred, separated by commas."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18765/v1")
    parser.add_argument("--model", default="smollm2-135m-q4-k-m")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "measurements"
    )
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output directory must be empty to preserve previous measurements")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # A length stop at 8 checks the requested max_completion_tokens field.
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "max_completion_tokens": 8,
    }
    request = urllib.request.Request(
        completion_url(args.base_url),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        probe = json.load(response)
    (args.output_dir / "probe.json").write_text(
        json.dumps({"request": payload, "response": probe}, indent=2) + "\n",
        encoding="utf-8",
    )
    if (
        probe["usage"]["completion_tokens"] != 8
        or probe["choices"][0]["finish_reason"] != "length"
        or not probe["choices"][0]["message"]["content"]
    ):
        raise RuntimeError("The backend did not satisfy the token-limit probe")

    rows = []
    # Alternate and reverse the order to reduce a fixed concurrency/order confound.
    for index, concurrency in enumerate((1, 2, 2, 1, 1, 2), start=1):
        report = run_benchmark(
            BenchmarkConfig(
                base_url=args.base_url,
                model=args.model,
                prompt=PROMPT,
                requests=8,
                concurrency=concurrency,
                warmup=1,
                max_completion_tokens=16,
                timeout_seconds=60,
            )
        )
        filename = f"trial-{index:02d}-c{concurrency}.json"
        (args.output_dir / filename).write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        summary = report["summary"]
        rows.append(
            {
                "report": filename,
                "concurrency": concurrency,
                "successful_requests": summary["successful_requests"],
                "failed_requests": summary["failed_requests"],
                "mean_latency_ms": summary["latency_ms"]["mean"],
                "successful_requests_per_second": summary[
                    "successful_requests_per_second"
                ],
                "completion_tokens_per_second": summary["completion_tokens_per_second"],
                "requests_reporting_output_limit_tokens": sum(
                    result["completion_tokens"] == 16 for result in report["results"]
                ),
            }
        )
        print(filename, summary["successful_requests"], "successful", flush=True)
    (args.output_dir / "overview.json").write_text(
        json.dumps(
            {
                "purpose": "real-backend compatibility, not a hardware capacity claim",
                "client": {
                    "architecture": platform.machine(),
                    "logical_cpus": os.cpu_count(),
                    "macos_version": platform.mac_ver()[0],
                    "python_version": platform.python_version(),
                },
                "trials": rows,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if any(row["failed_requests"] for row in rows):
        raise SystemExit(
            "Failures were retained in the reports; inspect before publishing"
        )


if __name__ == "__main__":
    main()
