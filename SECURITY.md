# Security policy

## Supported versions

Only the latest release (0.2.0, the version in `pyproject.toml`) on `main` receives security
fixes.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
(Security tab, "Report a vulnerability") or email thealirazadev@gmail.com with the
steps to reproduce. You should get a reply within 72 hours.

## How agent-trace-viewer protects trace data

- The HTML report contains no JavaScript and no server component; it is a static file you
  choose where to write.
- Every value from a trace (trace ids, step names, error messages, `detail` contents, and the
  report title) is HTML-escaped when rendered, so trace text cannot inject markup into the report.
- A malformed trace line stops the run with `file:line: reason` instead of being skipped, so
  bad input is visible rather than silently dropped.
- Prices are never built in. A step whose model has no `--price` shows `-` rather than a
  guessed cost.
- The tool reads local JSONL or OTLP/JSON files and makes no network requests while rendering
  or summarising them.
