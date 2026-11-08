from pathlib import Path

import pytest

from agent_trace_viewer.cli import main

EXAMPLE = Path(__file__).parents[1] / "examples" / "support-agent.jsonl"


def test_summary_prints_one_line_per_trace(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--price", "claude-sonnet-5-5=3,15", "summary", str(EXAMPLE)]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:4] == ["trace", "model", "tools", "errors"]
    assert len(lines) == 4  # header plus three traces
    assert all("$" in line for line in lines[1:])


def test_render_writes_a_self_contained_report(tmp_path: Path) -> None:
    out = tmp_path / "report.html"

    assert main(["render", str(EXAMPLE), "-o", str(out), "--title", "Support <agent>"]) == 0

    page = out.read_text()
    assert page.startswith("<!doctype html>")
    assert "<script" not in page and "http" not in page.split("</style>")[0]
    assert "Support &lt;agent&gt;" in page  # titles and store text are escaped
    assert "<details open>" in page  # traces with a failed step start expanded


def test_store_text_in_details_is_escaped(tmp_path: Path) -> None:
    trace = tmp_path / "t.jsonl"
    trace.write_text(
        '{"trace_id": "x", "kind": "tool", "name": "search", "latency_ms": 1,'
        ' "detail": {"query": "<img src=x onerror=alert(1)>"}}\n'
    )
    out = tmp_path / "r.html"

    assert main(["render", str(trace), "-o", str(out)]) == 0
    assert "<img" not in out.read_text()


def test_errors_exit_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{}\n")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")

    assert main(["summary", str(bad)]) == 2
    assert "bad.jsonl:1:" in capsys.readouterr().err
    assert main(["summary", str(empty)]) == 1
    assert main(["summary", str(tmp_path / "missing.jsonl")]) == 2
    assert main(["--price", "nope", "summary", str(EXAMPLE)]) == 2
