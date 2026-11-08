"""Read OpenTelemetry traces exported as OTLP/JSON, following the GenAI semantic conventions.

Accepts what the OpenTelemetry Collector's file exporter writes (one ExportTraceServiceRequest
per line) or a single pretty-printed export. Model calls and tool executions become steps;
every other span (agent wrappers, HTTP, database) is skipped.
"""

import base64
import binascii
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from agent_trace_viewer.traces import Step, TraceError

MODEL_OPERATIONS = {"chat", "text_completion", "generate_content", "completion"}
TOOL_OPERATIONS = {"execute_tool"}
STATUS_ERROR = (2, "STATUS_CODE_ERROR")


_HEX_ID = re.compile(r"[0-9a-fA-F]{32}")


def trace_hex(raw: str) -> str:
    """OTLP/JSON writes ids as hex; protobuf's generic JSON mapping writes base64. Show hex."""
    if _HEX_ID.fullmatch(raw):
        return raw.lower()
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return raw
    return decoded.hex() if len(decoded) == 16 else raw


def looks_like_otlp(text: str) -> bool:
    return '"resourceSpans"' in text[:4096]


def _value(raw: Mapping[str, Any]) -> Any:
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in raw:
            return raw[key]
    if "intValue" in raw:
        return int(raw["intValue"])  # OTLP/JSON encodes 64-bit integers as strings
    if "arrayValue" in raw:
        return [_value(item) for item in raw["arrayValue"].get("values", [])]
    return None


def _attributes(span: Mapping[str, Any]) -> dict[str, Any]:
    return {a["key"]: _value(a.get("value", {})) for a in span.get("attributes", []) if "key" in a}


def _requests(text: str, path: Path) -> Iterator[Mapping[str, Any]]:
    stripped = text.strip()
    try:
        yield json.loads(stripped)
        return
    except json.JSONDecodeError:
        pass
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceError(f"{path}:{number}: invalid JSON ({exc.msg})") from exc


def _tokens(attrs: Mapping[str, Any], key: str) -> int:
    value = attrs.get(key, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _step(span: Mapping[str, Any]) -> tuple[int, Step] | None:
    attrs = _attributes(span)
    operation = attrs.get("gen_ai.operation.name")
    if operation in TOOL_OPERATIONS or (operation is None and "gen_ai.tool.name" in attrs):
        kind, name = "tool", attrs.get("gen_ai.tool.name") or span.get("name")
    elif operation in MODEL_OPERATIONS:
        kind = "model"
        name = attrs.get("gen_ai.response.model") or attrs.get("gen_ai.request.model")
    else:
        return None
    try:
        start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
        trace_id = trace_hex(str(span["traceId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceError(f"span {span.get('name')!r} lacks traceId or timestamps") from exc
    status = span.get("status") or {}
    error = None
    if status.get("code") in STATUS_ERROR:
        error = status.get("message") or attrs.get("error.type") or "error"
    detail = {"span": span.get("name"), "operation": operation}
    if "gen_ai.tool.call.id" in attrs:
        detail["tool_call_id"] = attrs["gen_ai.tool.call.id"]
    if "gen_ai.response.finish_reasons" in attrs:
        detail["finish_reasons"] = attrs["gen_ai.response.finish_reasons"]
    return start, Step(
        trace_id=trace_id,
        kind=kind,
        name=str(name or "unknown"),
        latency_ms=max(0, round((end - start) / 1_000_000)),
        input_tokens=_tokens(attrs, "gen_ai.usage.input_tokens"),
        output_tokens=_tokens(attrs, "gen_ai.usage.output_tokens"),
        error=str(error) if error else None,
        detail={k: v for k, v in detail.items() if v is not None},
    )


def read_otlp(path: Path, text: str) -> list[Step]:
    """Steps from every GenAI span, ordered by trace (first seen) and then start time."""
    found: list[tuple[int, int, Step]] = []
    for request in _requests(text, path):
        for resource in request.get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    parsed = _step(span)
                    if parsed is not None:
                        found.append((parsed[0], len(found), parsed[1]))
    order: dict[str, int] = {}
    for _start, _, first in sorted(found, key=lambda item: (item[0], item[1])):
        order.setdefault(first.trace_id, len(order))
    found.sort(key=lambda item: (order[item[2].trace_id], item[0], item[1]))
    return [step for _, _, step in found]
