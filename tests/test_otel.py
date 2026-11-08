import json
from pathlib import Path
from typing import Any

import pytest

from agent_trace_viewer.cli import main
from agent_trace_viewer.otel import trace_hex
from agent_trace_viewer.traces import TraceError, read_steps, summarise

EXAMPLE = Path(__file__).parents[1] / "examples" / "otel-export.json"


def span(
    name: str, attrs: dict[str, Any], start: int, end: int, trace: str = "ab" * 16, **extra: Any
) -> dict[str, Any]:
    values = []
    for key, value in attrs.items():
        if isinstance(value, int):
            values.append({"key": key, "value": {"intValue": str(value)}})
        else:
            values.append({"key": key, "value": {"stringValue": value}})
    return {
        "traceId": trace,
        "name": name,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": values,
        **extra,
    }


def export(*spans: dict[str, Any]) -> str:
    return json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]})


def test_a_real_sdk_export_becomes_steps(tmp_path: Path) -> None:
    steps = read_steps(EXAMPLE)

    assert [(s.kind, s.name) for s in steps] == [
        ("model", "claude-sonnet-5-5"),
        ("tool", "get_order"),
    ] * 2
    assert all(len(s.trace_id) == 32 for s in steps)
    assert steps[0].input_tokens == 1200 and steps[0].output_tokens == 80
    assert steps[0].detail["finish_reasons"] == ["tool_use"]
    assert steps[3].error == "Shopify timed out"
    assert steps[3].detail["tool_call_id"] == "toolu_1"
    summaries = summarise(steps)
    assert [s.errors for s in summaries] == [0, 1]


def test_collector_jsonl_with_hex_ids_and_unrelated_spans(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    first = export(
        span(
            "chat",
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "m",
                "gen_ai.response.model": "m-2026",
                "gen_ai.usage.input_tokens": 7,
            },
            2_000_000,
            7_000_000,
        ),
        span("GET /", {"http.method": "GET"}, 0, 1),
    )
    second = export(
        span(
            "tool",
            {"gen_ai.tool.name": "search"},
            1_000_000,
            3_000_000,
            trace="CD" * 16,
            status={"code": "STATUS_CODE_ERROR"},
        ),
    )
    path.write_text(first + "\n\n" + second + "\n")

    steps = read_steps(path)

    assert [(s.trace_id, s.kind, s.name, s.latency_ms) for s in steps] == [
        ("cd" * 16, "tool", "search", 2),
        ("ab" * 16, "model", "m-2026", 5),
    ]
    assert steps[0].error == "error"
    assert steps[1].input_tokens == 7 and steps[1].output_tokens == 0


def test_bad_otlp_input_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text(export() + "\n{not json\n")
    with pytest.raises(TraceError, match=r"broken\.jsonl:2"):
        read_steps(broken)

    no_time = tmp_path / "no_time.json"
    no_time.write_text(
        export(
            {
                "name": "chat",
                "traceId": "x",
                "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}],
            }
        )
    )
    with pytest.raises(TraceError, match="timestamps"):
        read_steps(no_time)


def test_trace_ids_are_shown_as_hex() -> None:
    assert trace_hex("AB" * 16) == "ab" * 16
    assert trace_hex("+tXvLU5caH6VzqT2PbXcWg==") == "fad5ef2d4e5c687e95cea4f63db5dc5a"
    assert trace_hex("conv-1") == "conv-1"
    assert trace_hex("YWJj") == "YWJj"  # valid base64, but not a 16-byte id


def test_the_cli_reads_otlp_files(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", str(EXAMPLE)]) == 0
    assert "fad5ef2d4e5c687e95cea4f63db5dc5a" in capsys.readouterr().out
