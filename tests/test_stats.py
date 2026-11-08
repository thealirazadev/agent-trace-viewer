from pathlib import Path

import pytest

from agent_trace_viewer.cli import main
from agent_trace_viewer.traces import Step, percentile, step_stats

EXAMPLES = Path(__file__).parents[1] / "examples"


def step(name: str, ms: int, kind: str = "tool", error: str | None = None) -> Step:
    return Step("t", kind, name, ms, input_tokens=2, output_tokens=1, error=error)


def test_nearest_rank_percentiles() -> None:
    values = list(range(1, 101))
    assert percentile(values, 0.5) == 50
    assert percentile(values, 0.95) == 95
    assert percentile([7], 0.95) == 7
    assert percentile([], 0.5) == 0


def test_stats_group_by_name_and_put_the_slowest_first() -> None:
    steps = [step("search", ms) for ms in (10, 20, 30, 400)]
    steps += [step("llm", 900, kind="model"), step("search", 50, error="timeout")]

    stats = step_stats(steps)

    assert [(s.name, s.calls, s.errors) for s in stats] == [("llm", 1, 0), ("search", 5, 1)]
    search = stats[1]
    assert (search.p50_ms, search.p95_ms, search.max_ms) == (30, 400, 400)
    assert (search.input_tokens, search.output_tokens) == (10, 5)


def test_the_stats_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["stats", str(EXAMPLES / "support-agent.jsonl")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:4] == ["step", "kind", "calls", "errors"]
    assert lines[1].startswith("get_order") and "1 (100%)" in lines[1]
