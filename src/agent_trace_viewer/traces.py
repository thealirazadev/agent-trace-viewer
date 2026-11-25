"""Parse trace JSONL (docs/decisions.md, decision 1) and summarise each trace."""

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

KINDS = ("model", "tool")
MTOK = Decimal(1_000_000)


class TraceError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    trace_id: str
    kind: str
    name: str
    latency_ms: int
    turn: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: Decimal
    output: Decimal


@dataclass
class Summary:
    trace_id: str
    steps: list[Step]
    model_calls: int = 0
    tool_calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: Decimal | None = None


def _int(raw: Mapping[str, Any], key: str, default: int | None = None) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceError(f"'{key}' must be a non-negative integer")
    return value


def _str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise TraceError(f"'{key}' must be a non-empty string")
    return value


def parse_step(raw: Any) -> Step:
    if not isinstance(raw, dict):
        raise TraceError("each line must be a JSON object")
    kind = _str(raw, "kind")
    if kind not in KINDS:
        raise TraceError(f"'kind' must be one of {', '.join(KINDS)}, not '{kind}'")
    error = raw.get("error")
    if error is not None and not isinstance(error, str):
        raise TraceError("'error' must be a string")
    detail = raw.get("detail", {})
    if not isinstance(detail, dict):
        raise TraceError("'detail' must be an object")
    trace_id = raw.get("trace_id")
    if isinstance(trace_id, int) and not isinstance(trace_id, bool):
        raw = {**raw, "trace_id": str(trace_id)}  # numeric ids, such as eval case numbers
    return Step(
        trace_id=_str(raw, "trace_id"),
        kind=kind,
        name=_str(raw, "name"),
        latency_ms=_int(raw, "latency_ms"),
        turn=_int(raw, "turn", 0),
        input_tokens=_int(raw, "input_tokens", 0),
        output_tokens=_int(raw, "output_tokens", 0),
        error=error or None,
        detail=detail,
    )


def read_steps(path: Path) -> list[Step]:
    """Every step in the file, in order. A bad line fails with ``path:line: reason``.

    OpenTelemetry OTLP/JSON exports are detected and read with ``otel.read_otlp``.
    """
    text = path.read_text(encoding="utf-8")
    from agent_trace_viewer import otel  # imports Step from here

    if otel.looks_like_otlp(text):
        return otel.read_otlp(path, text)
    steps = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            steps.append(parse_step(json.loads(line)))
        except json.JSONDecodeError as exc:
            raise TraceError(f"{path}:{number}: invalid JSON ({exc.msg})") from exc
        except TraceError as exc:
            raise TraceError(f"{path}:{number}: {exc}") from exc
    return steps


def summarise(steps: Iterable[Step], prices: Mapping[str, Price] | None = None) -> list[Summary]:
    """One summary per trace, in first-seen order. Cost needs a price for every model used."""
    by_trace: dict[str, Summary] = {}
    for step in steps:
        summary = by_trace.setdefault(step.trace_id, Summary(step.trace_id, []))
        summary.steps.append(step)
        summary.model_calls += step.kind == "model"
        summary.tool_calls += step.kind == "tool"
        summary.errors += step.error is not None
        summary.input_tokens += step.input_tokens
        summary.output_tokens += step.output_tokens
        summary.latency_ms += step.latency_ms
    if prices:
        for summary in by_trace.values():
            summary.cost_usd = trace_cost(summary.steps, prices)
    return list(by_trace.values())


@dataclass(frozen=True)
class StepStats:
    kind: str
    name: str
    calls: int
    errors: int
    p50_ms: int
    p95_ms: int
    max_ms: int
    input_tokens: int
    output_tokens: int


def percentile(sorted_values: list[int], fraction: float) -> int:
    """Nearest-rank percentile: a value that actually occurred, never an interpolation."""
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def step_stats(steps: Iterable[Step]) -> list[StepStats]:
    """Per model and tool name across every trace, slowest p95 first."""
    groups: dict[tuple[str, str], list[Step]] = {}
    for step in steps:
        groups.setdefault((step.kind, step.name), []).append(step)
    stats = []
    for (kind, name), group in groups.items():
        latencies = sorted(s.latency_ms for s in group)
        stats.append(
            StepStats(
                kind,
                name,
                len(group),
                sum(s.error is not None for s in group),
                percentile(latencies, 0.5),
                percentile(latencies, 0.95),
                latencies[-1],
                sum(s.input_tokens for s in group),
                sum(s.output_tokens for s in group),
            )
        )
    return sorted(stats, key=lambda s: (-s.p95_ms, s.kind, s.name))


def trace_cost(steps: Iterable[Step], prices: Mapping[str, Price]) -> Decimal | None:
    total = Decimal(0)
    for step in steps:
        if step.kind != "model":
            continue
        price = prices.get(step.name)
        if price is None:
            return None  # an unpriced model makes the total wrong, so show none
        total += (step.input_tokens * price.input + step.output_tokens * price.output) / MTOK
    return total


def parse_price(text: str) -> tuple[str, Price]:
    """``MODEL=IN,OUT`` in USD per million tokens."""
    model, _, rates = text.partition("=")
    parts = rates.split(",")
    if not model or len(parts) != 2:
        raise TraceError(f"price '{text}' must look like MODEL=IN,OUT")
    try:
        price = Price(Decimal(parts[0]), Decimal(parts[1]))
    except ArithmeticError as exc:
        raise TraceError(f"price '{text}' has a rate that is not a number") from exc
    if not (price.input.is_finite() and price.output.is_finite()):
        raise TraceError(f"price '{text}' has a rate that is not a number")
    if price.input < 0 or price.output < 0:
        raise TraceError(f"price '{text}' has a negative rate")
    return model, price
