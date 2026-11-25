from decimal import Decimal
from pathlib import Path

import pytest

from agent_trace_viewer.traces import (
    Price,
    TraceError,
    parse_price,
    read_steps,
    summarise,
)

LINES = [
    '{"trace_id": "a", "kind": "model", "name": "m1", "latency_ms": 900,'
    ' "input_tokens": 1000000, "output_tokens": 100000}',
    '{"trace_id": "a", "kind": "tool", "name": "search", "latency_ms": 40}',
    "",
    '{"trace_id": "b", "kind": "tool", "name": "get_order", "latency_ms": 10, "error": "timeout"}',
]


def write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_steps_group_into_traces_with_totals(tmp_path: Path) -> None:
    [a, b] = summarise(read_steps(write(tmp_path, LINES)))

    assert (a.trace_id, a.model_calls, a.tool_calls, a.latency_ms) == ("a", 1, 1, 940)
    assert (b.errors, b.cost_usd) == (1, None)


def test_cost_needs_a_price_for_every_model(tmp_path: Path) -> None:
    steps = read_steps(write(tmp_path, LINES))

    [a, _] = summarise(steps, {"m1": Price(Decimal(3), Decimal(15))})
    [unpriced, _] = summarise(steps, {"other": Price(Decimal(3), Decimal(15))})

    assert a.cost_usd == Decimal("4.5")  # 1M in at $3 + 0.1M out at $15
    assert unpriced.cost_usd is None


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("not json", "invalid JSON"),
        ("[1]", "JSON object"),
        ('{"trace_id": "a", "kind": "agent", "name": "x", "latency_ms": 1}', "'kind'"),
        ('{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": -1}', "'latency_ms'"),
        ('{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": true}', "'latency_ms'"),
        ('{"kind": "tool", "name": "x", "latency_ms": 1}', "'trace_id'"),
        ('{"trace_id": "a", "kind": "tool", "name": "", "latency_ms": 1}', "'name'"),
        ('{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": 1, "detail": 3}', "detail"),
        ('{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": 1, "error": 5}', "'error'"),
    ],
)
def test_bad_lines_fail_with_their_line_number(tmp_path: Path, line: str, reason: str) -> None:
    path = write(tmp_path, [LINES[1], line])

    with pytest.raises(TraceError, match=rf":2: .*{reason}"):
        read_steps(path)


def test_numeric_trace_ids_are_accepted(tmp_path: Path) -> None:
    [step] = read_steps(
        write(tmp_path, ['{"trace_id": 7, "kind": "tool", "name": "x", "latency_ms": 1}'])
    )
    assert step.trace_id == "7"


def test_parse_price() -> None:
    assert parse_price("claude=3,15") == ("claude", Price(Decimal(3), Decimal(15)))
    for bad in (
        "claude",
        "=3,15",
        "claude=3",
        "claude=a,b",
        "claude=-1,2",
        "claude=nan,1",
        "claude=3,inf",
    ):
        with pytest.raises(TraceError):
            parse_price(bad)


def test_null_error_means_no_error(tmp_path: Path) -> None:
    # Shopwright's export emits "error": null for steps that succeeded.
    line = '{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": 1, "error": null}'
    [step] = read_steps(write(tmp_path, [line]))
    assert step.error is None


def test_empty_error_means_no_error(tmp_path: Path) -> None:
    line = '{"trace_id": "a", "kind": "tool", "name": "x", "latency_ms": 1, "error": ""}'
    [step] = read_steps(write(tmp_path, [line]))
    assert step.error is None
    assert summarise([step])[0].errors == 0
