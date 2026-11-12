"""Transport, request outcomes, and closed-loop benchmark measurements."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import platform
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from inference_bench import __version__

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def completion_url(base_url: str) -> str:
    """Accept a versioned API base URL without credentials or query parameters."""
    parts = urllib.parse.urlsplit(base_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(character.isspace() for character in base_url)
    ):
        raise ValueError(
            "base URL must be http(s), without credentials, query or fragment"
        )
    try:
        _ = parts.port
    except ValueError as error:
        raise ValueError("base URL has an invalid port") from error
    return base_url.rstrip("/") + "/chat/completions"


@dataclass(frozen=True)
class BenchmarkConfig:
    base_url: str
    model: str
    prompt: str
    requests: int = 10
    concurrency: int = 1
    warmup: int = 1
    max_completion_tokens: int = 64
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        completion_url(self.base_url)
        if not self.model.strip() or not self.prompt.strip():
            raise ValueError("model and prompt must not be empty")
        for name in ("requests", "concurrency", "max_completion_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.warmup) is not int or self.warmup < 0:
            raise ValueError("warmup must be a non-negative integer")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class RequestResult:
    request_id: int
    latency_ms: float
    status_code: int | None
    error: str | None
    completion_tokens: int | None = None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A benchmark must measure its selected endpoint and retain its auth there.
        return None


def perform_request(
    request_id: int, config: BenchmarkConfig, api_key: str | None = None
) -> RequestResult:
    payload = json.dumps(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": config.prompt}],
            "max_completion_tokens": config.max_completion_tokens,
            "stream": False,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        completion_url(config.base_url), data=payload, headers=headers, method="POST"
    )
    opener = urllib.request.build_opener(_NoRedirects())
    status_code = None
    error = None
    tokens = None
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=config.timeout_seconds) as response:
            status_code = response.status
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                error = "response_too_large"
            else:
                data = json.loads(body)
                choices = data.get("choices") if isinstance(data, dict) else None
                if (
                    not isinstance(choices, list)
                    or not choices
                    or not isinstance(choices[0], dict)
                    or not isinstance(choices[0].get("message"), dict)
                    or not isinstance(choices[0]["message"].get("content"), str)
                ):
                    error = "invalid_response"
                else:
                    usage = data.get("usage")
                    count = (
                        usage.get("completion_tokens")
                        if isinstance(usage, dict)
                        else None
                    )
                    if type(count) is int and count >= 0:
                        tokens = count
    except urllib.error.HTTPError as exception:
        status_code = exception.code
        error = "http_error"
        exception.close()
    except TimeoutError:
        error = "timeout"
    except urllib.error.URLError as exception:
        error = (
            "timeout" if isinstance(exception.reason, TimeoutError) else "network_error"
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        error = "invalid_response"
    except http.client.IncompleteRead:
        error = "incomplete_response"
    except (OSError, http.client.HTTPException):
        error = "network_error"
    latency_ms = (time.perf_counter() - started) * 1000
    return RequestResult(request_id, latency_ms, status_code, error, tokens)


def percentile(values: list[float], fraction: float) -> float | None:
    """Linearly interpolate sorted samples at (n - 1) * fraction."""
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between zero and one")
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(results: list[RequestResult], elapsed_seconds: float) -> dict[str, Any]:
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be finite and positive")
    successful = [result for result in results if result.error is None]
    latencies = [result.latency_ms for result in successful]
    counts = [
        result.completion_tokens
        for result in successful
        if result.completion_tokens is not None
    ]
    complete_usage = bool(successful) and len(counts) == len(successful)
    return {
        "requests": len(results),
        "successful_requests": len(successful),
        "failed_requests": len(results) - len(successful),
        "error_rate": (len(results) - len(successful)) / len(results) if results else 0,
        "errors": dict(Counter(result.error for result in results if result.error)),
        "elapsed_seconds": elapsed_seconds,
        "successful_requests_per_second": len(successful) / elapsed_seconds,
        "latency_ms": {
            "mean": statistics.mean(latencies) if latencies else None,
            "min": min(latencies) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies) if latencies else None,
        },
        "requests_with_token_usage": len(counts),
        "observed_completion_tokens": sum(counts),
        "completion_tokens_per_second": (
            sum(counts) / elapsed_seconds if complete_usage else None
        ),
    }


def run_benchmark(
    config: BenchmarkConfig, api_key: str | None = None
) -> dict[str, Any]:
    warmups = [perform_request(i, config, api_key) for i in range(config.warmup)]
    workers = min(config.concurrency, config.requests)
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lambda index: perform_request(index, config, api_key),
                range(config.requests),
            )
        )
    elapsed = time.perf_counter() - started
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "started_at": started_at,
        "python_version": platform.python_version(),
        "config": {
            "base_url": config.base_url.rstrip("/"),
            "model": config.model,
            "prompt_sha256": hashlib.sha256(config.prompt.encode("utf-8")).hexdigest(),
            "requests": config.requests,
            "concurrency": config.concurrency,
            "effective_concurrency": workers,
            "warmup": config.warmup,
            "max_completion_tokens": config.max_completion_tokens,
            "timeout_seconds": config.timeout_seconds,
            "stream": False,
        },
        "warmup": {
            "requests": len(warmups),
            "failed_requests": sum(result.error is not None for result in warmups),
        },
        "summary": summarize(results, elapsed),
        "results": [asdict(result) for result in results],
    }
