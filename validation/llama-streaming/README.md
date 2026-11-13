# Local streaming compatibility validation

Collected November 13, 2026 against a real CPU inference server on the same
shared Intel Mac as the client. **This is a compatibility smoke test, not a
capacity, GPU, latency ranking, or reliable p99 study.** No paid service was used.
Original non-streaming evidence was not modified.

All 16 measured requests and four excluded warmups succeeded. Every measured
response supplied a nonempty content delta, a supported finish reason, DONE,
and a server-reported usage count of 16 completion tokens. The four trials
used concurrency 1, 2, 2, 1 with four measured requests per trial. Model quality
was not evaluated. Small samples and shared host load prohibit comparisons.

| Trial | Concurrency | Successes | Mean first-content (ms) | Mean complete latency (ms) |
| --- | --- | --- | --- | --- |
| 1 | 1 | 4/4 | 300.24 | 503.15 |
| 2 | 2 | 4/4 | 370.73 | 734.42 |
| 3 | 2 | 4/4 | 380.15 | 759.97 |
| 4 | 1 | 4/4 | 249.51 | 475.29 |

First-content timing includes HTTP setup, prompt processing, generation,
transport and parsing up to the first nonempty text delta. A delta can contain
multiple tokens; this is not a measurement of a server's first generated token.
Full latency ends after parsing DONE. Usage counts are trusted, not retokenized.
Reports deliberately omit generated text and the prompt itself (only its hash).

## Conditions

- Client: Python 3.12.16, macOS x86_64. See the measured platform string and
  SHA-256 of each client source file in [environment.json](measurements/environment.json).
- Backend: official llama.cpp build `b12110`, `0.9.0-dev`, commit `cd959bae9`,
  macOS-x64 binary. The downloaded archive and extracted regular files were
  verified before execution. Archive SHA-256:
  `c8094268b6bf62f4998f0e45656fd9f5e2d4afb6b1cd0044d761db64be1dd47d`.
- Model: `bartowski/SmolLM2-135M-Instruct-GGUF`, revision
  `09816acd5d99df7be770d85ea30822623dab342c`, file
  `SmolLM2-135M-Instruct-Q4_K_M.gguf`, 105,454,432 bytes, SHA-256
  `2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`.
- Two generation threads, two batch threads, two slots, 2,048 total context
  tokens, zero GPU layers, no operation offload. Prompt caching and idle-slot
  cache saving disabled; RAM prompt-cache size zero. Temperature zero, seed 42.
  The server launch supplies `--n-predict 32`; client requests use a limit of 16.
- Loopback endpoint `http://127.0.0.1:18765/v1`, alias `smollm2-135m-q4-k-m`.
  The public counting prompt is embedded in the collector. Socket timeout 60s.
  Model loading and each sequential warmup are outside the measured run timer.
- The host was not isolated from other applications. CPU brand and installed
  RAM were not measured. The temporary server was terminated after collection
  and its loopback port was verified closed.

## Reproduction

Install this branch's client, then obtain and run the pinned model/backend using
the [fail-fast, checksum-verified launch recipe](https://github.com/lighthuska-lab/inference-bench/blob/cc36164809dd01ac757cea44a673fcdf640113d3/validation/llama-cpu/README.md#reproduce-without-overwriting-the-evidence).
That recipe uses the exact flags and pinned artifacts above. It requires an
Intel Mac; other platforms are outside this retained evidence.

From another terminal in the repository, run:

```bash
python validation/llama-streaming/run_validation.py \
  --output-dir results/llama-streaming-reproduction
```

The collector refuses an existing output directory and retains partial reports
on failure. Stop the server after collection. Verify the committed artifacts
from this directory with `shasum -a 256 -c SHA256SUMS`. These checksums detect
changes to retained artifacts; they are not signatures or independent review.

## Protocol references

- [WHATWG SSE parsing](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation)
- [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Backend release](https://github.com/ggml-org/llama.cpp/releases/tag/b12110)
- [Pinned model files](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/tree/09816acd5d99df7be770d85ea30822623dab342c)
