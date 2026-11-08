"""Render summaries as a terminal table or one self-contained HTML file (no JS, no network)."""

import json
from collections.abc import Sequence
from decimal import Decimal
from html import escape

from agent_trace_viewer.traces import StepStats, Summary


def _cost(value: Decimal | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _columns(header: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> str:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]

    def line(cells: tuple[str, ...]) -> str:
        first = cells[0].ljust(widths[0])
        rest = (c.rjust(w) for c, w in zip(cells[1:], widths[1:], strict=True))
        return "  ".join([first, *rest]).rstrip()

    return "\n".join([line(header), *(line(r) for r in rows)])


def stats_table(stats: list[StepStats]) -> str:
    header = ("step", "kind", "calls", "errors", "p50", "p95", "max", "tokens in", "tokens out")
    rows = [
        (
            s.name,
            s.kind,
            str(s.calls),
            f"{s.errors} ({100 * s.errors / s.calls:.0f}%)" if s.errors else "0",
            f"{s.p50_ms:,} ms",
            f"{s.p95_ms:,} ms",
            f"{s.max_ms:,} ms",
            f"{s.input_tokens:,}",
            f"{s.output_tokens:,}",
        )
        for s in stats
    ]
    return _columns(header, rows)


def table(summaries: list[Summary]) -> str:
    header = ("trace", "model", "tools", "errors", "tokens in", "tokens out", "latency", "cost")
    rows = [
        (
            s.trace_id,
            str(s.model_calls),
            str(s.tool_calls),
            str(s.errors),
            f"{s.input_tokens:,}",
            f"{s.output_tokens:,}",
            f"{s.latency_ms:,} ms",
            _cost(s.cost_usd),
        )
        for s in summaries
    ]
    return _columns(header, rows)


STYLE = """
:root { --bg: #fafafa; --fg: #1a1a1a; --muted: #666; --line: #e2e2e2; --card: #fff;
  --model: #3b5bdb; --tool: #2b8a3e; --error: #c92a2a; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #141414; --fg: #eaeaea; --muted: #9a9a9a; --line: #2e2e2e; --card: #1c1c1c;
    --model: #748ffc; --tool: #69db7c; --error: #ff8787; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 14px/1.45 system-ui, sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
.muted { color: var(--muted); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { font-size: 12px; color: var(--muted); font-weight: 500; }
details { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  margin: 12px 0; }
summary { cursor: pointer; padding: 10px 12px; }
.steps { padding: 0 12px 12px; overflow-x: auto; }
.bar { height: 8px; border-radius: 2px; min-width: 2px; }
.model .bar { background: var(--model); }
.tool .bar { background: var(--tool); }
.failed .bar { background: var(--error); }
.kind { font-size: 12px; color: var(--muted); }
.err { color: var(--error); }
pre { margin: 4px 0 0; white-space: pre-wrap; word-break: break-word; font-size: 12px;
  color: var(--muted); }
.track { position: relative; width: 240px; }
.tot { font-variant-numeric: tabular-nums; }
"""


def _step_rows(summary: Summary) -> str:
    total = max(summary.latency_ms, 1)
    offset = 0
    rows = []
    for step in summary.steps:
        # Waterfall: steps in a trace run in sequence, so each bar starts where the last ended.
        left, width = offset / total * 100, step.latency_ms / total * 100
        offset += step.latency_ms
        css = f"{step.kind}{' failed' if step.error else ''}"
        detail = json.dumps(step.detail, sort_keys=True) if step.detail else ""
        note = f'<div class="err">{escape(step.error)}</div>' if step.error else ""
        extra = f"<pre>{escape(detail)}</pre>" if detail else ""
        rows.append(
            f'<tr class="{css}"><td>{step.turn}</td>'
            f'<td style="text-align:left"><span class="kind">{step.kind}</span> '
            f"{escape(step.name)}{note}{extra}</td>"
            f'<td class="track"><div class="bar" style="margin-left:{left:.2f}%;'
            f'width:{width:.2f}%"></div></td>'
            f'<td class="tot">{step.latency_ms:,} ms</td>'
            f'<td class="tot">{step.input_tokens:,} / {step.output_tokens:,}</td></tr>'
        )
    return "".join(rows)


def html(summaries: list[Summary], title: str) -> str:
    totals = (
        sum(s.model_calls for s in summaries),
        sum(s.tool_calls for s in summaries),
        sum(s.errors for s in summaries),
        sum(s.input_tokens + s.output_tokens for s in summaries),
    )
    costs = [s.cost_usd for s in summaries]
    cost = None if None in costs else sum((c for c in costs if c is not None), Decimal(0))
    overview = "".join(
        f"<tr><td>{escape(s.trace_id)}</td><td>{s.model_calls}</td><td>{s.tool_calls}</td>"
        f'<td class="{"err" if s.errors else ""}">{s.errors}</td>'
        f"<td>{s.input_tokens + s.output_tokens:,}</td><td>{s.latency_ms:,} ms</td>"
        f"<td>{_cost(s.cost_usd)}</td></tr>"
        for s in summaries
    )
    traces = "".join(
        f"<details{' open' if s.errors else ''}><summary><strong>{escape(s.trace_id)}</strong>"
        f' <span class="muted">{len(s.steps)} steps, {s.latency_ms:,} ms'
        f"{', ' + str(s.errors) + ' failed' if s.errors else ''}</span></summary>"
        '<div class="steps"><table><tr><th>Turn</th><th style="text-align:left">Step</th>'
        "<th>Timeline</th><th>Latency</th><th>Tokens in / out</th></tr>"
        f"{_step_rows(s)}</table></div></details>"
        for s in summaries
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><main>"
        f"<h1>{escape(title)}</h1>"
        f'<p class="muted">{_plural(len(summaries), "trace")} · '
        f"{_plural(totals[0], 'model call')} · {_plural(totals[1], 'tool call')} · "
        f"{_plural(totals[2], 'error')} · {totals[3]:,} tokens · cost {_cost(cost)}</p>"
        "<table><tr><th>Trace</th><th>Model</th><th>Tools</th><th>Errors</th><th>Tokens</th>"
        f"<th>Latency</th><th>Cost</th></tr>{overview}</table>{traces}</main></body></html>\n"
    )
