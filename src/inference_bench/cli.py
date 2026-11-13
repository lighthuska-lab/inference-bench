"""Command-line interface. JSON goes to stdout and diagnostics to stderr."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from inference_bench import __version__
from inference_bench.benchmark import BenchmarkConfig, run_benchmark

CSV_COLUMNS = (
    "request_id",
    "latency_ms",
    "status_code",
    "error",
    "completion_tokens",
)


@contextmanager
def _report_path(target: Path | None) -> Iterator[Path | None]:
    if target is None:
        yield None
        return
    if target.is_dir():
        raise ValueError("output must be a file, not a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Check directory access before sending requests, and replace reports atomically.
    with tempfile.TemporaryDirectory(
        prefix=".inference-bench-", dir=target.parent
    ) as tmp:
        yield Path(tmp) / "report.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark an OpenAI-compatible Chat Completions API."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--base-url", required=True, help="API base, including /v1")
    parser.add_argument(
        "--model", required=True, help="Model ID served by the endpoint"
    )
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument("--prompt", default=None)
    prompts.add_argument(
        "--prompt-file", type=Path, help="Read a UTF-8 prompt from disk"
    )
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument(
        "--stream", action="store_true", help="Measure streaming first-content latency"
    )
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-completion-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS")
    parser.add_argument(
        "--output", type=Path, help="Also save the JSON report to this file"
    )
    parser.add_argument(
        "--csv-output", type=Path, help="Save measured request outcomes as CSV"
    )
    args = parser.parse_args(argv)
    try:
        prompt = (
            args.prompt_file.read_text(encoding="utf-8")
            if args.prompt_file
            else (
                args.prompt
                if args.prompt is not None
                else "Explain what inference latency means in one sentence."
            )
        )
        config = BenchmarkConfig(
            base_url=args.base_url,
            model=args.model,
            prompt=prompt,
            requests=args.requests,
            concurrency=args.concurrency,
            warmup=args.warmup,
            max_completion_tokens=args.max_completion_tokens,
            timeout_seconds=args.timeout,
            stream=args.stream,
        )
        if args.output is not None and args.csv_output is not None:
            json_output = args.output.resolve()
            csv_output = args.csv_output.resolve()
            if (
                json_output == csv_output
                or json_output in csv_output.parents
                or csv_output in json_output.parents
            ):
                raise ValueError(
                    "JSON and CSV output paths must be separate, not nested"
                )
        with (
            _report_path(args.output) as json_path,
            _report_path(args.csv_output) as csv_path,
        ):
            report = run_benchmark(config, os.environ.get("INFERENCE_BENCH_API_KEY"))
            encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
            if json_path is not None:
                json_path.write_text(encoded, encoding="utf-8")
            if csv_path is not None:
                with csv_path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(CSV_COLUMNS)
                    # The runner returns measured results in request_id order.
                    for result in report["results"]:
                        writer.writerow(result[column] for column in CSV_COLUMNS)
            if json_path is not None:
                json_path.replace(args.output)
            if csv_path is not None:
                csv_path.replace(args.csv_output)
        sys.stdout.write(encoded)
        return 1 if report["summary"]["failed_requests"] else 0
    except (ValueError, OSError):
        print(
            "Invalid configuration or unreadable/unwritable file. "
            "Check URL, positive numeric options, prompt, and output paths.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        return 130
