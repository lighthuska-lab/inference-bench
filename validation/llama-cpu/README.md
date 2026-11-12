# First real-backend validation: llama.cpp on an Intel Mac

Collected on November 12, 2026. This is a small **compatibility validation**, not
an estimate of hardware capacity, a GPU benchmark, or a comparison of providers.
It closes the mock-only evidence gap in [issue #2](https://github.com/lighthuska-lab/inference-bench/issues/2).

## Scope and results

The client completed 48 measured requests across six trials, with zero failures.
Each trial had eight measured requests and one excluded warmup. All warmups
succeeded. Trial order was 1, 2, 2, 1, 1, 2 for concurrency. The model was actually
loaded and generating tokens in llama.cpp, not replaced with a mock response.

| Trial | Concurrency | Successes | Mean latency (ms) | Successful requests/s | Completion tokens/s |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 8/8 | 554.74 | 1.75 | 28.03 |
| 2 | 2 | 8/8 | 819.33 | 2.38 | 38.06 |
| 3 | 2 | 8/8 | 546.38 | 3.58 | 57.22 |
| 4 | 1 | 8/8 | 266.44 | 3.63 | 58.05 |
| 5 | 1 | 8/8 | 263.49 | 3.67 | 58.65 |
| 6 | 2 | 8/8 | 579.33 | 3.35 | 53.62 |

Every measured response reported 16 completion tokens. A separate
[direct probe](measurements/probe.json) requested eight tokens and returned
`finish_reason: length`, eight completion tokens, 43 prompt tokens, and zero cached
prompt tokens. Individual benchmark records do not include finish reasons, so
we do not assert a stop reason for every measured response. Text quality was not
assessed. The public counting prompt is a workload, not a quality test.

A separate installed-CLI smoke run produced two successful requests and matching
[JSON](measurements/cli-smoke.json) and [CSV](measurements/cli-smoke.csv) output.
Token counts and exported rows were checked. No paid API or rented infrastructure
was used. The temporary localhost server was stopped after collection.

The first trial was substantially slower than later concurrency-1 trials. This
shared developer machine was not isolated from other applications. Do not infer
that either concurrency level is faster in general. Eight samples per trial
are too few for reliable p99 analysis. Raw percentiles are retained, not promoted
as stable performance estimates.

## Recorded conditions

1. Tool source: [9c38ec9](https://github.com/lighthuska-lab/inference-bench/tree/9c38ec919c04af9eebb716bffc74a6a1e8df8191),
   Python 3.12.16, macOS 26.7.2, x86_64, eight logical CPUs visible. The sandbox
   denied CPU-brand and installed-RAM queries, so those details are unknown.
2. Backend: official llama.cpp macOS-x64 binary from build `b12110`, reporting
   `0.9.0-dev (build 12110, commit cd959bae9)`. Two generation threads, two batch
   threads, two slots, 2,048 total context tokens (1,024 per slot), and zero GPU
   layers. The client and server were on the same host over loopback HTTP.
3. Model: `bartowski/SmolLM2-135M-Instruct-GGUF`, revision
   `09816acd5d99df7be770d85ea30822623dab342c`, file
   `SmolLM2-135M-Instruct-Q4_K_M.gguf`, 105,454,432 bytes. This is a Q4_K_M
   quantization of `HuggingFaceTB/SmolLM2-135M-Instruct`. Tokenizer and chat-template
   data are embedded in the pinned GGUF file. Counts were taken from the server,
   not recomputed with a different tokenizer.
4. Sampling: temperature zero, seed 42, non-streaming, client output limit 16,
   socket timeout 60 seconds. The launch command supplied `--n-predict 32`.
   `/props` reported `n_predict: -1` in its default parameter object. Both values
   are recorded rather than treating the launch flag as proof of a server-wide
   hard cap. The direct probe verifies the request's `max_completion_tokens` limit.
5. Prompt caching and idle-slot cache saving were disabled in the server command,
   with RAM prompt-cache size zero. The direct probe reported zero cached tokens.
   Full-model loading and all warmups were outside the measured trial timers.

See [environment.json](environment.json) for the structured manifest,
[server-startup.txt](server-startup.txt) for the sanitized startup log, and
[measurements](measurements) for all raw reports. Only the local model path was
replaced with `$MODEL_FILE` in the startup log. Binaries and weights are not
redistributed here. llama.cpp is MIT-licensed and the model card identifies the
weights as Apache-2.0.

## Reproduce without overwriting the evidence

Download the pinned artifacts into a temporary directory. These commands use the
macOS-x64 build and standard `shasum` available on macOS. The block runs in a
separate Bash process with fail-fast checks. A failed download or checksum stops
it before extraction or execution.

```bash
bash <<'BASH'
set -euo pipefail
BACKEND_DIR="$(mktemp -d)"
curl --fail --location \
  https://github.com/ggml-org/llama.cpp/releases/download/b12110/llama-b12110-bin-macos-x64.tar.gz \
  --output "$BACKEND_DIR/llama.tar.gz"
curl --fail --location \
  https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/09816acd5d99df7be770d85ea30822623dab342c/SmolLM2-135M-Instruct-Q4_K_M.gguf \
  --output "$BACKEND_DIR/model.gguf"
printf '%s  %s\n' \
  c8094268b6bf62f4998f0e45656fd9f5e2d4afb6b1cd0044d761db64be1dd47d \
  "$BACKEND_DIR/llama.tar.gz" | shasum -a 256 -c -
printf '%s  %s\n' \
  2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d \
  "$BACKEND_DIR/model.gguf" | shasum -a 256 -c -
tar -xzf "$BACKEND_DIR/llama.tar.gz" -C "$BACKEND_DIR"
"$BACKEND_DIR/llama-b12110/llama-server" \
  --model "$BACKEND_DIR/model.gguf" \
  --host 127.0.0.1 --port 18765 --alias smollm2-135m-q4-k-m \
  --threads 2 --threads-batch 2 --parallel 2 --ctx-size 2048 \
  --n-gpu-layers 0 --no-op-offload --no-cache-prompt \
  --cache-ram 0 --no-cache-idle-slots --n-predict 32 \
  --temp 0 --seed 42 --offline
BASH
```

From the repository in another terminal, install the client following the README,
then use a fresh output directory:

```bash
python validation/llama-cpu/run_trials.py \
  --output-dir results/llama-cpu-reproduction
```

The committed trials were collected with the script's default endpoint, model,
and workload settings. The collector refuses a nonempty output directory so it
cannot silently replace previous evidence. This collector is for the unauthenticated
loopback server above. It does not load an API key or follow a remote deployment
recipe. Stop your server with Ctrl-C when finished.

The installed-CLI smoke command used during collection was:

```bash
inference-bench \
  --base-url http://127.0.0.1:18765/v1 --model smollm2-135m-q4-k-m \
  --prompt 'List the integers from one through one hundred, separated by commas.' \
  --requests 2 --concurrency 2 --warmup 0 --max-completion-tokens 16 --timeout 60 \
  --output validation/llama-cpu/measurements/cli-smoke.json \
  --csv-output validation/llama-cpu/measurements/cli-smoke.csv
```

For a new run, change those output paths to a fresh directory under `results/`.
To verify the retained evidence, run `shasum -a 256 -c SHA256SUMS` from this
validation directory. Future reruns should be saved separately, with their own
conditions and hashes. Compatibility beyond this backend/model combination,
streaming, and performance under sustained load remain unvalidated.

## Sources

- [llama.cpp build b12110](https://github.com/ggml-org/llama.cpp/releases/tag/b12110)
- [Pinned quantized model](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/tree/09816acd5d99df7be770d85ea30822623dab342c)
- [Original model](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct)
