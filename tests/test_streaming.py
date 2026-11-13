from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import threading
import unittest
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from inference_bench.benchmark import (
    BenchmarkConfig,
    RequestResult,
    perform_request,
    read_completion_stream,
    summarize,
)
from inference_bench.cli import CSV_COLUMNS, main
from inference_bench.streaming import StreamTooLarge, events


def event(delta=None, *, finish=None, usage=None):
    choices = [] if delta is None else [{"delta": delta, "finish_reason": finish}]
    return (
        "data: " + json.dumps({"choices": choices, "usage": usage}) + "\n\n"
    ).encode()


def complete(*, usage=True, text="hello"):
    body = event({"role": "assistant"}) + event({"content": ""})
    body += event({"content": text}) + event({}, finish="stop")
    if usage:
        body += event(usage={"completion_tokens": 2})
    return body + b"data: [DONE]\n\n"


class Fragmented(io.BytesIO):
    def __init__(self, value, width=1):
        super().__init__(value)
        self.width = width
        self.headers = Message()
        self.headers["Content-Type"] = "text/event-stream; charset=utf-8"

    def read1(self, size=-1):
        return super().read1(min(size, self.width))


class FramingTests(unittest.TestCase):
    def test_all_newlines_and_bytewise_utf8(self):
        for ending in (b"\r", b"\n", b"\r\n"):
            raw = ending.join(
                [
                    "\ufeff: heartbeat".encode(),
                    b"id: 1",
                    b"event: message",
                    "data: café".encode(),
                    b"data: next",
                    b"",
                    b"",
                ]
            )
            with self.subTest(ending=ending):
                self.assertEqual(list(events(Fragmented(raw), 1024)), ["café\nnext"])

    def test_eof_does_not_dispatch_unfinished_event(self):
        for raw in (b"data: [DONE]", b"data: [DONE]\n"):
            self.assertEqual(list(events(Fragmented(raw), 100)), [])

    def test_empty_data_dispatches_but_comments_do_not(self):
        self.assertEqual(list(events(Fragmented(b": ping\n\ndata:\n\n"), 100)), [""])

    def test_invalid_utf8_and_trailing_bytes_fail(self):
        for raw in (b"data: \xff\n\n", b": trailing \xff"):
            with self.assertRaises(UnicodeDecodeError):
                list(events(Fragmented(raw), 100))

    def test_total_limit_includes_comments_and_unterminated_lines(self):
        for raw in (b": ignored\n\n" * 20, b"data: " + b"x" * 100):
            with self.assertRaises(StreamTooLarge):
                list(events(Fragmented(raw), 32))


class StreamTests(unittest.TestCase):
    def test_first_nonempty_content_only_stops_timer_once(self):
        # The only clock read must occur on actual nonempty content, even with
        # later content. A second call exhausts side_effect and fails the test.
        raw = complete(text="first").replace(
            event({}, finish="stop"),
            event({"content": "second"}) + event({}, finish="stop"),
        )
        with patch("inference_bench.benchmark.time.perf_counter", side_effect=[12.5]):
            first, tokens = read_completion_stream(Fragmented(raw), 10)
        self.assertEqual(first, 2500)
        self.assertEqual(tokens, 2)

    def test_no_content_or_missing_usage_remains_unknown(self):
        first, tokens = read_completion_stream(
            Fragmented(complete(text="", usage=False)), 0
        )
        self.assertIsNone(first)
        self.assertIsNone(tokens)

    def test_zero_usage_preserved_invalid_usage_not_estimated(self):
        for count in (0, True, -1, "2", 1.5):
            raw = complete().replace(
                b'"completion_tokens": 2',
                json.dumps({"completion_tokens": count}).encode()[1:-1],
            )
            with self.subTest(count=count):
                _, tokens = read_completion_stream(Fragmented(raw), 0)
                self.assertEqual(
                    tokens, 0 if type(count) is int and count == 0 else None
                )

    def test_malformed_and_unsupported_events_fail(self):
        bad = [
            b"data: nope\n\n",
            b"data: []\n\n",
            b"data: {}\n\n",
            b'data: {"error":{"message":"secret"}}\n\n',
            event({"content": ["not text"]}),
            event({"tool_calls": [{"id": "x"}]}),
            event({}, finish="tool_calls"),
            event(usage={"completion_tokens": 2}),
            b"data: [DONE]\n\n",
            event({}, finish="stop") + event({"content": "late"}),
        ]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_completion_stream(Fragmented(raw), 0)

    def test_summary_uses_successful_nonnull_samples_only(self):
        results = [
            RequestResult(0, 10, 200, None, 2, 3),
            RequestResult(1, 20, 200, None),
            RequestResult(2, 30, None, "timeout", None, 999),
        ]
        report = summarize(results, 1)
        self.assertEqual(report["first_content_ms"]["samples"], 1)
        self.assertEqual(report["first_content_ms"]["p50"], 3)
        self.assertIsNone(report["completion_tokens_per_second"])
        self.assertEqual(summarize([], 1)["first_content_ms"]["samples"], 0)


class Endpoint:
    def __init__(
        self, body=None, *, content_type="text/event-stream", stall=False, staged=False
    ):
        self.body = complete() if body is None else body
        self.requests = []
        self.release = threading.Event()
        self.role_sent = threading.Event()
        self.send_content = threading.Event()
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                endpoint.requests.append(
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                )
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(endpoint.body)))
                self.end_headers()
                if staged:
                    prefix = event({"role": "assistant"})
                    self.wfile.write(prefix)
                    self.wfile.flush()
                    endpoint.role_sent.set()
                    endpoint.send_content.wait(3)
                    content = event({"content": "hello"})
                    self.wfile.write(content)
                    self.wfile.flush()
                    endpoint.release.wait(3)
                    self.wfile.write(endpoint.body[len(prefix + content) :])
                    return
                if stall:
                    endpoint.release.wait(2)
                    return
                self.wfile.write(endpoint.body)
                self.wfile.flush()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.release.set()
        self.send_content.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class HttpTests(unittest.TestCase):
    def config(self, endpoint, **kwargs):
        return BenchmarkConfig(
            endpoint.url, "local", "synthetic", stream=True, **kwargs
        )

    def test_success_payload_and_latency(self):
        with Endpoint() as endpoint:
            result = perform_request(0, self.config(endpoint))
        self.assertIsNone(result.error)
        self.assertEqual(result.completion_tokens, 2)
        self.assertGreaterEqual(result.first_content_ms, 0)
        self.assertLessEqual(result.first_content_ms, result.latency_ms)
        self.assertTrue(endpoint.requests[0]["stream"])
        self.assertEqual(
            endpoint.requests[0]["stream_options"], {"include_usage": True}
        )

    def test_first_content_observed_before_server_finishes(self):
        raw = event({"role": "assistant"}) + event({"content": "hello"})
        raw += event({}, finish="stop") + b"data: [DONE]\n\n"
        observed = threading.Event()
        calls = []
        results = []

        def clock():
            calls.append(len(calls))
            if len(calls) == 2:
                observed.set()
            return len(calls)

        with Endpoint(raw, staged=True) as endpoint:
            with patch(
                "inference_bench.benchmark.time.perf_counter", side_effect=clock
            ):
                worker = threading.Thread(
                    target=lambda: results.append(
                        perform_request(0, self.config(endpoint))
                    )
                )
                worker.start()
                try:
                    self.assertTrue(endpoint.role_sent.wait(2))
                    self.assertEqual(len(calls), 1)
                    endpoint.send_content.set()
                    self.assertTrue(
                        observed.wait(2), "reader buffered content until EOF"
                    )
                finally:
                    endpoint.release.set()
                    worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].first_content_ms, 1000)

    def test_truncation_missing_done_wrong_mime_and_malformed(self):
        cases = [
            (
                complete().replace(b"data: [DONE]\n\n", b""),
                "text/event-stream",
                "incomplete_response",
            ),
            (complete(), "application/json", "invalid_response"),
            (b"data: secret-invalid-json\n\n", "text/event-stream", "invalid_response"),
        ]
        for raw, mime, error in cases:
            with (
                self.subTest(error=error),
                Endpoint(raw, content_type=mime) as endpoint,
            ):
                result = perform_request(0, self.config(endpoint))
                self.assertEqual(result.error, error)
                self.assertIsNone(result.completion_tokens)
                self.assertIsNone(result.first_content_ms)

    def test_timeout_and_size_limit(self):
        with Endpoint(stall=True) as endpoint:
            self.assertEqual(
                perform_request(0, self.config(endpoint, timeout_seconds=0.05)).error,
                "timeout",
            )
        with Endpoint(b": " + b"x" * 100) as endpoint:
            with patch("inference_bench.benchmark.MAX_RESPONSE_BYTES", 32):
                self.assertEqual(
                    perform_request(0, self.config(endpoint)).error,
                    "response_too_large",
                )

    def test_cli_json_csv_warmup_and_content_privacy(self):
        with Endpoint() as endpoint, tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "out.csv"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(
                    [
                        "--base-url",
                        endpoint.url,
                        "--model",
                        "local",
                        "--stream",
                        "--requests",
                        "2",
                        "--warmup",
                        "1",
                        "--csv-output",
                        str(csv_path),
                    ]
                )
            self.assertEqual(status, 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report["config"]["stream"])
            self.assertEqual(report["summary"]["first_content_ms"]["samples"], 2)
            self.assertEqual(len(endpoint.requests), 3)
            self.assertNotIn("hello", output.getvalue())
            with csv_path.open() as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], list(CSV_COLUMNS))
            self.assertEqual(len(rows), 3)

    def test_stream_config_requires_bool(self):
        with self.assertRaises(ValueError):
            BenchmarkConfig("http://localhost/v1", "m", "p", stream="yes")
