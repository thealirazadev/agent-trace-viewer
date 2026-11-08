# Design decisions

## 1. One JSONL line per step

A trace is the list of steps one agent run took. Each line is one step:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `trace_id` | string | yes | Groups steps into one run (a conversation turn, an eval case) |
| `kind` | `model` or `tool` | yes | A model call or a tool call |
| `name` | string | yes | Model id or tool name |
| `latency_ms` | integer >= 0 | yes | Wall time of the step |
| `turn` | integer | no | Turn number inside the trace, default 0 |
| `input_tokens`, `output_tokens` | integer >= 0 | no | Provider-reported usage, default 0 |
| `error` | string | no | Set when the step failed |
| `detail` | object | no | Anything else (tool input, stop reason); shown as JSON |

JSONL streams, appends, and greps well, and every agent framework can write it. Shopwright's
`traces` table has these columns already, so its export is one SQL query (see README).

## 2. Static HTML, no server

`atv render` writes one self-contained HTML file: inline CSS, no JavaScript, no network. It can
be attached to a pull request, uploaded as a CI artifact, or opened from disk. A live viewer
would need a server and a build step for the same information.

## 3. Strict parsing with line numbers

A malformed line fails the run with `file:line: reason`, rather than being skipped. A trace
viewer that silently drops steps would hide exactly the failures it exists to show.

## 4. Cost is opt-in

Prices change and differ by model, so the tool never hardcodes them. Pass
`--price MODEL=IN,OUT` (USD per million tokens) to add cost columns; without it, the report shows
tokens only.

## 5. No dependencies

The standard library covers JSON, HTML escaping, and argument parsing. Nothing to audit or
upgrade.

- **OpenTelemetry as the second input format.** It is the vendor-neutral way agent frameworks
  export traces, and the GenAI conventions name exactly the fields `atv` needs. Only GenAI spans
  become steps, so a full application trace stays readable. The format is detected from the
  file, so there is no flag to forget.
- **Nearest-rank percentiles.** With a handful of calls, interpolated percentiles invent
  latencies that never happened; nearest-rank always reports a real one.
