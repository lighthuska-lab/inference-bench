# inference-bench

[![CI](https://github.com/lighthuska-lab/inference-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/lighthuska-lab/inference-bench/actions/workflows/ci.yml)

Measure non-streaming latency, throughput, and failures for an OpenAI-compatible
Chat Completions endpoint. Run a fixed number of requests with bounded concurrency
and save individual outcomes alongside summary statistics.

The Python runtime has no third-party dependencies. Python 3.11 or newer is required.
This is an original project maintained by Light Huska, not an OpenAI product.

## Try it locally

```bash
git clone https://github.com/lighthuska-lab/inference-bench.git
cd inference-bench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Start the mock endpoint in one terminal:

```bash
python examples/mock_server.py
```

In another terminal with the virtual environment activated:

```bash
inference-bench \
  --base-url http://127.0.0.1:8000/v1 \
  --model mock-model \
  --requests 20 \
  --concurrency 4 \
  --warmup 2 \
  --output results/mock-run.json \
  --csv-output results/mock-run.csv
```

`--csv-output` writes one row per measured request in request ID order. Failed
requests are included, warmups are excluded, and unavailable values are empty.
JSON still goes to stdout and can also be saved with `--output`. Use different
paths for the JSON and CSV files.

The mock replies with fixed text and token counts. Its numbers test the client
and protocol only. They are **not model, GPU, or server performance evidence**.
See [the example report](examples/mock-report.json) for the JSON layout.

## Benchmark your own endpoint

Use the versioned API base URL and a model identifier that the server actually
serves. The client appends `/chat/completions` and sends `stream: false` with
`max_completion_tokens`. Servers that only accept the older `max_tokens` field
are not supported yet. This is not an Azure deployment-specific client or a
Responses API client.

```bash
# Optional: export INFERENCE_BENCH_API_KEY through your secret manager or shell.
inference-bench \
  --base-url http://127.0.0.1:8000/v1 \
  --model YOUR_SERVED_MODEL_ID \
  --prompt-file examples/prompt.txt \
  --requests 100 \
  --concurrency 4 \
  --warmup 5 \
  --max-completion-tokens 128 \
  --timeout 30 \
  --output results/run.json
```

The CLI also prints the full JSON report to stdout. Diagnostics go to stderr.
Exit codes are `0` for all measured requests succeeding, `1` for any measured
request failure, `2` for invalid options or file errors, and `130` for interruption.
Warmup failures are reported separately and do not change the exit status.

The key is read from `INFERENCE_BENCH_API_KEY`, not a command-line option. Reports
contain a prompt hash rather than prompt text, and do not contain the key,
generated text, or server error bodies. Model names and the base URL are included
in reports, so inspect them before sharing. Use HTTPS for remote authenticated
endpoints. Redirects are rejected. No retries are performed.

## What the numbers mean

1. Latency measures wall time inside each HTTP attempt, including connection
   setup, reading the entire response, and JSON validation. It excludes time
   queued in the client executor. Percentiles use linear interpolation at
   `(n - 1) * fraction` and include successful requests only. Failure latencies
   remain in the individual results.
2. Successful requests per second equals successful measured requests divided by
   the whole measured run duration, including worker startup and shutdown.
   Warmup requests run sequentially before that timer and are excluded.
3. Completion tokens per second equals the sum of server-reported completion
   tokens on successful requests divided by measured run duration. It is `null`
   unless **every successful request** reports a valid token count. Missing
   usage is not estimated from characters. A reported zero is kept as zero.
4. Concurrency is a maximum number of active requests in a closed-loop client.
   Requests are replaced as they finish, not sent at a fixed arrival rate. The
   effective concurrency is capped by the measured request count.
5. `--timeout` is a socket-operation timeout, not a strict end-to-end deadline.
   A server that trickles bytes can keep a request alive longer. Responses above
   8 MiB are rejected. There is no streaming, time-to-first-token, per-token
   latency, quality scoring, connection pooling, or GPU utilization measurement.

All-failed runs have `null` latency percentiles and token throughput. A successful
response must have a JSON `choices[0].message.content` string. Tool-only or
multimodal responses are outside this first version.

Repeated prompts may benefit from backend prefix caching. Results depend on
client hardware, network distance, server/model version, load, batching, caching,
and output lengths. Record those conditions alongside a report. Small runs are
smoke tests, not reliable p99 comparisons. See [the methodology](docs/methodology.md).

## Develop and collaborate

```bash
python -m pip install -e . ruff==0.14.4 build==1.3.0
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
python -m build
```

Tests run against local HTTP fixtures and need no API key, GPU, model download,
or external inference service. CI runs the same checks on Python 3.11–3.14.
One [local llama.cpp CPU configuration](validation/llama-cpu/README.md) has been
validated with real model inference. This does not establish compatibility with
every provider or model.

CSV export was contributed by [Jeff Walsh](https://github.com/jeffwalsh728-tech)
in [PR #3](https://github.com/lighthuska-lab/inference-bench/pull/3). Follow
[the teammate guide](docs/teamwork.md) and [CONTRIBUTING.md](CONTRIBUTING.md) for
review and attribution expectations. Streaming metrics remain future work.
This repository is not published on PyPI.

## License

[MIT](LICENSE). Keep contributor attribution accurate. Existing work is credited
to its authors, and co-author trailers are used only for actual shared work.
