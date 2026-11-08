"""``atv summary FILE`` prints a table; ``atv render FILE -o report.html`` writes a report."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_trace_viewer.render import html, table
from agent_trace_viewer.traces import TraceError, parse_price, read_steps, summarise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atv", description=__doc__)
    parser.add_argument(
        "--price",
        action="append",
        default=[],
        metavar="MODEL=IN,OUT",
        help="USD per million input and output tokens for a model; repeat per model",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary", help="print one line per trace")
    summary.add_argument("file", type=Path)
    render = sub.add_parser("render", help="write a self-contained HTML report")
    render.add_argument("file", type=Path)
    render.add_argument("-o", "--output", type=Path, required=True)
    render.add_argument("--title", default="")
    args = parser.parse_args(argv)

    try:
        prices = dict(parse_price(p) for p in args.price)
        summaries = summarise(read_steps(args.file), prices)
    except (TraceError, OSError) as exc:
        print(f"atv: {exc}", file=sys.stderr)
        return 2

    if not summaries:
        print(f"atv: {args.file} has no steps", file=sys.stderr)
        return 1
    if args.command == "summary":
        print(table(summaries))
        return 0
    try:
        args.output.write_text(html(summaries, args.title or args.file.name), encoding="utf-8")
    except OSError as exc:
        print(f"atv: cannot write {args.output}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.output} ({len(summaries)} traces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
