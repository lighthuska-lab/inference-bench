# Measurement boundaries

Use an endpoint you own or have permission to load test. Begin with a small
request count and low concurrency. Warmups and failed requests can still incur
provider charges. This project does not make paid calls during its own tests.

The client sends a single user message with `stream: false`. A request starts
when a worker begins its HTTP attempt and ends when the response has been read
and validated. The run timer starts before worker creation and ends after all
measured attempts finish. No requests are retried or followed across redirects.

The HTTP client opens a connection for each request. It includes connection
overhead and does not isolate model compute time. Measurements are client-observed
end-to-end behavior, not a server capacity ceiling or an open-loop load test.

Server usage is trusted rather than retokenized. `completion_tokens` can include
reasoning or other backend-specific tokens. Compare token rates only when the
server's counting semantics match. A completion can hit its output limit and
still count as a successful protocol response. Success does not measure quality.

## Reproduce a real run

Record the tool commit, Python version, client CPU/OS, network placement, endpoint
implementation/version, model ID and revision, tokenizer, hardware, quantization,
server configuration, cache policy, request count, concurrency, warmup count,
output limit, prompt source, and the command used. Sanitize private details before
publishing them. The JSON report records only part of this information.

Run multiple trials for each configuration. Change one relevant factor at a time
and retain failures. Inspect raw results rather than comparing p99 from a handful
of requests. Do not compare mock data with real inference measurements.

## Report schema version 1

`config` describes the workload, including the SHA-256 of the UTF-8 prompt text.
`warmup` counts excluded attempts and their failures. `summary` aggregates only
measured requests. `results` has one record per measured attempt, with
`request_id`, `latency_ms`, `status_code`, `error`, and `completion_tokens`.
Missing values are JSON `null`. Error categories are `http_error`, `network_error`,
`timeout`, `invalid_response`, `incomplete_response`, and `response_too_large`.

Warmup failures do not abort the run. Socket timeouts are not absolute deadlines.
Interrupting a run waits for outstanding workers to return before process exit.
No partial report is promised after interruption.

The [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
describes the request and usage fields. Compatible servers can differ, so record
backend-specific behavior and validate a real run before making performance claims.
