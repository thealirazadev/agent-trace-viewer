# Changelog

## 0.2.0 - 2026-11-09

- Reads OpenTelemetry OTLP/JSON exports that follow the GenAI semantic conventions (model calls
  and tool executions; hex or base64 trace ids; array attributes). Verified against the
  OpenTelemetry Python SDK's encoder; an example export is in `examples/`.
- `atv stats`: calls, errors, p50/p95/max latency, and tokens per model and tool, slowest first.
- CI on Linux, macOS, and Windows with Python 3.11 and 3.13; coverage gate at 95 percent.

## 0.1.0

JSONL trace format, `atv summary`, and the self-contained HTML report.
