from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from inference_bench.benchmark import (
    BenchmarkConfig,
    RequestResult,
    completion_url,
    percentile,
    perform_request,
    run_benchmark,
    summarize,
)
from inference_bench.cli import main


class LocalEndpoint:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.status = 200
        self.body = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": "Synthetic"}}],
                "usage": {"completion_tokens": 3},
            }
        ).encode()
        self.barrier: threading.Barrier | None = None
        self.redirect: str | None = None
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                endpoint.requests.append(json.loads(body))
                endpoint.headers.append(dict(self.headers))
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                if endpoint.barrier:
                    endpoint.barrier.wait(timeout=5)
                self.send_response(endpoint.status)
                if endpoint.redirect:
                    self.send_header("Location", endpoint.redirect)
                self.send_header("Content-Length", str(len(endpoint.body)))
                self.end_headers()
                self.wfile.write(endpoint.body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class ConfigurationTests(unittest.TestCase):
    def test_versioned_base_and_trailing_slash(self):
        self.assertEqual(
            completion_url("http://localhost:8000/v1/"),
            "http://localhost:8000/v1/chat/completions",
        )

    def test_unsafe_or_invalid_urls(self):
        for url in (
            "ftp://host/v1",
            "http:///v1",
            "https://user:password@host/v1",
            "https://host/v1?key=secret",
            "https://host/v1#secret",
            "http://host:broken/v1",
            "http://host:99999/v1",
            "http://host/with space",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                completion_url(url)

    def test_positive_parameters(self):
        for field in ("requests", "concurrency", "max_completion_tokens"):
            for value in (0, -1, True, 1.5):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        BenchmarkConfig(
                            "http://host/v1", "model", "prompt", **{field: value}
                        )

    def test_timeout_warmup_and_text_validation(self):
        cases = [
            {"warmup": -1},
            {"warmup": True},
            {"timeout_seconds": 0},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"model": " "},
            {"prompt": ""},
        ]
        for changes in cases:
            values = {"base_url": "http://host/v1", "model": "m", "prompt": "p"}
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                BenchmarkConfig(**values)


class SummaryTests(unittest.TestCase):
    def test_percentiles_use_linear_interpolation(self):
        self.assertEqual(percentile([40, 10, 30, 20], 0.50), 25)
        self.assertAlmostEqual(percentile([10, 20, 30, 40], 0.95), 38.5)
        self.assertEqual(percentile([8], 0.99), 8)
        self.assertIsNone(percentile([], 0.50))
        with self.assertRaises(ValueError):
            percentile([1], 2)

    def test_failures_do_not_improve_latency_or_successful_throughput(self):
        results = [
            RequestResult(0, 10, 200, None, 4),
            RequestResult(1, 30, 200, None, 6),
            RequestResult(2, 1, 429, "http_error"),
        ]
        summary = summarize(results, 2)
        self.assertEqual(summary["successful_requests_per_second"], 1)
        self.assertEqual(summary["latency_ms"]["mean"], 20)
        self.assertEqual(summary["completion_tokens_per_second"], 5)
        self.assertEqual(summary["errors"], {"http_error": 1})
        self.assertEqual(summary["failed_requests"], 1)
        self.assertAlmostEqual(summary["error_rate"], 1 / 3)

    def test_missing_usage_is_not_zero_or_estimated_throughput(self):
        summary = summarize(
            [RequestResult(0, 10, 200, None, 4), RequestResult(1, 20, 200, None)], 2
        )
        self.assertIsNone(summary["completion_tokens_per_second"])
        self.assertEqual(summary["observed_completion_tokens"], 4)
        self.assertEqual(summary["requests_with_token_usage"], 1)

    def test_all_failed_and_no_samples(self):
        for results in ([], [RequestResult(0, 1, 500, "http_error")]):
            with self.subTest(results=results):
                summary = summarize(results, 1)
                self.assertEqual(summary["successful_requests_per_second"], 0)
                self.assertIsNone(summary["latency_ms"]["p95"])
                self.assertIsNone(summary["completion_tokens_per_second"])

    def test_zero_usage_is_a_real_measurement(self):
        summary = summarize([RequestResult(0, 10, 200, None, 0)], 1)
        self.assertEqual(summary["completion_tokens_per_second"], 0)

    def test_invalid_elapsed_duration(self):
        for duration in (0, -1, float("nan"), float("inf")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                summarize([], duration)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.endpoint = LocalEndpoint().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.endpoint.__exit__()

    def setUp(self):
        self.endpoint.requests.clear()
        self.endpoint.headers.clear()
        self.endpoint.status = 200
        self.endpoint.redirect = None
        self.endpoint.barrier = None
        self.endpoint.body = json.dumps(
            {
                "choices": [{"message": {"content": "Synthetic response"}}],
                "usage": {"completion_tokens": 3},
            }
        ).encode()
        self.config = BenchmarkConfig(
            self.endpoint.url, "mock-model", "private prompt", requests=4, warmup=0
        )

    def test_real_http_payload_and_auth(self):
        result = perform_request(7, self.config, "test-only-key")
        self.assertIsNone(result.error)
        self.assertEqual(result.request_id, 7)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.completion_tokens, 3)
        self.assertGreater(result.latency_ms, 0)
        self.assertEqual(
            self.endpoint.headers[0]["Authorization"], "Bearer test-only-key"
        )
        self.assertEqual(
            self.endpoint.requests[0],
            {
                "model": "mock-model",
                "messages": [{"role": "user", "content": "private prompt"}],
                "max_completion_tokens": 64,
                "stream": False,
            },
        )

    def test_http_error_retains_status_but_not_server_body(self):
        self.endpoint.status = 429
        self.endpoint.body = b"secret-server-diagnostic"
        result = perform_request(0, self.config)
        self.assertEqual(result.error, "http_error")
        self.assertEqual(result.status_code, 429)
        self.assertNotIn("secret", repr(result))

    def test_invalid_json_and_completion_shapes(self):
        for body in (
            b"not JSON",
            b"\xff",
            b"[]",
            b"{}",
            b'{"choices": []}',
            b'{"choices": [null]}',
            b'{"choices": [{"message": {"content": null}}]}',
        ):
            self.endpoint.body = body
            with self.subTest(body=body):
                self.assertEqual(
                    perform_request(0, self.config).error, "invalid_response"
                )

    def test_optional_and_invalid_token_counts(self):
        for usage in (None, {}, {"completion_tokens": True}, {"completion_tokens": -1}):
            self.endpoint.body = json.dumps(
                {"choices": [{"message": {"content": "ok"}}], "usage": usage}
            ).encode()
            with self.subTest(usage=usage):
                result = perform_request(0, self.config)
                self.assertIsNone(result.error)
                self.assertIsNone(result.completion_tokens)

    def test_redirect_is_not_followed_or_given_credentials(self):
        with LocalEndpoint() as target:
            self.endpoint.status = 307
            self.endpoint.redirect = target.url + "/chat/completions"
            result = perform_request(0, self.config, "test-only-key")
            self.assertEqual(result.status_code, 307)
            self.assertEqual(result.error, "http_error")
            self.assertEqual(target.requests, [])

    def test_oversized_response(self):
        self.endpoint.body = b"a" * 100
        with patch("inference_bench.benchmark.MAX_RESPONSE_BYTES", 32):
            result = perform_request(0, self.config)
        self.assertEqual(result.error, "response_too_large")

    def test_network_and_timeout_failures(self):
        for failure, category in (
            (urllib.error.URLError("offline"), "network_error"),
            (urllib.error.URLError(TimeoutError()), "timeout"),
            (TimeoutError(), "timeout"),
        ):
            with self.subTest(category=category):
                with patch("urllib.request.OpenerDirector.open", side_effect=failure):
                    self.assertEqual(perform_request(0, self.config).error, category)

    def test_warmups_excluded_and_sensitive_data_absent(self):
        config = BenchmarkConfig(
            self.endpoint.url, "mock-model", "private prompt", requests=3, warmup=2
        )
        report = run_benchmark(config, "test-only-key")
        self.assertEqual(len(self.endpoint.requests), 5)
        self.assertEqual(report["summary"]["requests"], 3)
        self.assertEqual(report["summary"]["observed_completion_tokens"], 9)
        self.assertEqual(report["warmup"], {"requests": 2, "failed_requests": 0})
        encoded = json.dumps(report)
        for secret in ("private prompt", "test-only-key", "Synthetic response"):
            self.assertNotIn(secret, encoded)

    def test_failed_warmups_are_visible_but_do_not_cancel_measured_requests(self):
        self.endpoint.status = 503
        config = BenchmarkConfig(self.endpoint.url, "m", "p", requests=2, warmup=1)
        report = run_benchmark(config)
        self.assertEqual(report["warmup"]["failed_requests"], 1)
        self.assertEqual(report["summary"]["failed_requests"], 2)
        self.assertEqual(len(self.endpoint.requests), 3)

    def test_parallel_requests_actually_overlap(self):
        self.endpoint.barrier = threading.Barrier(2)
        config = BenchmarkConfig(
            self.endpoint.url, "m", "p", requests=2, concurrency=2, warmup=0
        )
        report = run_benchmark(config)
        self.assertEqual(report["summary"]["successful_requests"], 2)
        self.assertEqual([r["request_id"] for r in report["results"]], [0, 1])

    def test_requested_concurrency_is_capped_by_request_count(self):
        config = BenchmarkConfig(
            self.endpoint.url, "m", "p", requests=1, concurrency=8, warmup=0
        )
        self.assertEqual(run_benchmark(config)["config"]["effective_concurrency"], 1)


class CliTests(unittest.TestCase):
    def test_output_directory_is_rejected_before_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("inference_bench.cli.run_benchmark") as run:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = main(
                        [
                            "--base-url",
                            "http://host/v1",
                            "--model",
                            "m",
                            "--output",
                            directory,
                        ]
                    )
            self.assertEqual(code, 2)
            run.assert_not_called()

    def test_existing_report_survives_failed_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            target.write_text("previous report", encoding="utf-8")
            with patch(
                "inference_bench.cli.run_benchmark",
                return_value={"value": float("nan")},
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = main(
                        [
                            "--base-url",
                            "http://host/v1",
                            "--model",
                            "m",
                            "--output",
                            str(target),
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertEqual(target.read_text(), "previous report")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_invalid_options_do_not_send_requests(self):
        cases = (
            ["--requests", "0"],
            ["--timeout", "nan"],
            ["--prompt", ""],
            ["--prompt-file", "/does-not-exist"],
        )
        for extra in cases:
            with self.subTest(extra=extra):
                with patch("inference_bench.cli.run_benchmark") as run:
                    with contextlib.redirect_stderr(io.StringIO()):
                        code = main(
                            ["--base-url", "http://host/v1", "--model", "m", *extra]
                        )
                    self.assertEqual(code, 2)
                    run.assert_not_called()

    def test_successful_json_file_and_stdout_with_unicode_prompt(self):
        with LocalEndpoint() as endpoint, tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "prompt.txt"
            prompt.write_text("Explain latency: 日本語", encoding="utf-8")
            output = Path(directory) / "reports" / "run.json"
            csv_output = output.with_suffix(".csv")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--base-url",
                        endpoint.url,
                        "--model",
                        "mock-model",
                        "--requests",
                        "2",
                        "--warmup",
                        "1",
                        "--prompt-file",
                        str(prompt),
                        "--output",
                        str(output),
                        "--csv-output",
                        str(csv_output),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(stdout.getvalue()), json.loads(output.read_text())
            )
            with csv_output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(endpoint.requests), 3)
            self.assertEqual([row["request_id"] for row in rows], ["0", "1"])
            self.assertEqual([row["completion_tokens"] for row in rows], ["3", "3"])
            self.assertEqual(
                endpoint.requests[0]["messages"][0]["content"], prompt.read_text()
            )

    def test_csv_rows_include_failures_and_leave_missing_values_empty(self):
        report = {
            "results": [
                {
                    "request_id": 0,
                    "latency_ms": 1.5,
                    "status_code": 200,
                    "error": None,
                    "completion_tokens": 0,
                    "content": "private response",
                },
                {
                    "request_id": 1,
                    "latency_ms": 2.5,
                    "status_code": 429,
                    "error": "http_error",
                    "completion_tokens": None,
                },
                {
                    "request_id": 2,
                    "latency_ms": 3.5,
                    "status_code": 200,
                    "error": None,
                    "completion_tokens": None,
                },
                {
                    "request_id": 3,
                    "latency_ms": 4.5,
                    "status_code": None,
                    "error": "timeout",
                    "completion_tokens": None,
                },
            ],
            "summary": {"failed_requests": 2},
            "warmup": {"requests": 3, "failed_requests": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "run.csv"
            with (
                patch("inference_bench.cli.run_benchmark", return_value=report),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = main(
                    [
                        "--base-url",
                        "http://host/v1",
                        "--model",
                        "m",
                        "--csv-output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 1)
            with output.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(
                    list(csv.reader(stream)),
                    [
                        [
                            "request_id",
                            "latency_ms",
                            "status_code",
                            "error",
                            "completion_tokens",
                        ],
                        ["0", "1.5", "200", "", "0"],
                        ["1", "2.5", "429", "http_error", ""],
                        ["2", "3.5", "200", "", ""],
                        ["3", "4.5", "", "timeout", ""],
                    ],
                )

    def test_invalid_csv_output_preserves_json_and_skips_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            json_output = Path(directory) / "run.json"
            json_output.write_text("previous report", encoding="utf-8")
            for csv_output in (
                directory,
                str(json_output / "nested"),
                str(json_output),
            ):
                with (
                    self.subTest(csv_output=csv_output),
                    patch("inference_bench.cli.run_benchmark") as run,
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    code = main(
                        [
                            "--base-url",
                            "http://host/v1",
                            "--model",
                            "m",
                            "--output",
                            str(json_output),
                            "--csv-output",
                            csv_output,
                        ]
                    )
                    self.assertEqual(code, 2)
                    run.assert_not_called()
                    self.assertEqual(json_output.read_text(), "previous report")

    def test_failed_request_yields_json_and_nonzero_exit(self):
        with LocalEndpoint() as endpoint:
            endpoint.status = 503
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--base-url",
                        endpoint.url,
                        "--model",
                        "m",
                        "--requests",
                        "1",
                        "--warmup",
                        "0",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue())["summary"]["failed_requests"], 1
            )

    def test_module_entrypoint(self):
        with LocalEndpoint() as endpoint:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "inference_bench",
                    "--base-url",
                    endpoint.url,
                    "--model",
                    "mock-model",
                    "--requests",
                    "1",
                    "--warmup",
                    "0",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=os.environ.copy(),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
