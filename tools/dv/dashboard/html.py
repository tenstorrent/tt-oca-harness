# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Small HTML rendering helpers for static dashboard pages."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

COVERAGE_FIELDS = (
    ("total", "Total"),
    ("line", "Line"),
    ("condition", "Condition"),
    ("toggle", "Toggle"),
    ("fsm_state", "FSM"),
    ("branch", "Branch"),
    ("assertion", "Assertion"),
    ("functional", "Functional"),
    ("expression", "Expression"),
    ("user", "User"),
)


STYLE = """
body {
  color: #202124;
  font-family: Arial, Helvetica, sans-serif;
  line-height: 1.45;
  margin: 2rem;
}
table {
  border-collapse: collapse;
  margin-top: 1rem;
  width: 100%;
}
th, td {
  border: 1px solid #d0d7de;
  padding: 0.45rem 0.6rem;
  text-align: left;
}
th {
  background: #f6f8fa;
}
.PASS {
  color: #116329;
  font-weight: 700;
}
.FAIL {
  color: #a40e26;
  font-weight: 700;
}
.UNKNOWN {
  color: #6e7781;
  font-weight: 700;
}
.accepted, .waive, .exclude_scope {
  color: #8250df;
  font-weight: 700;
}
.open, .cover, .fix_design, .fix_model, .review {
  color: #a40e26;
  font-weight: 700;
}
.meta {
  color: #57606a;
}
.cards {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  margin: 1rem 0;
}
.card {
  background: #fff;
  border: 1px solid #d0d7de;
  border-left: 0.35rem solid #7c68fa;
  border-radius: 0.35rem;
  padding: 0.8rem 1rem;
}
.card .label {
  color: #57606a;
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
}
.card .value {
  color: #202124;
  font-size: 1.8rem;
  font-weight: 700;
}
.small {
  font-size: 0.9rem;
}
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>{STYLE}</style>
</head>
<body>
{body}
</body>
</html>
"""


def link(path: str, label: str | None = None) -> str:
    if not path:
        return "--"
    label = label or Path(path).name or path
    parsed = urlparse(path)
    if parsed.scheme and parsed.scheme not in {"https", "http"}:
        return escape(label)
    return f'<a href="{escape(path)}">{escape(label)}</a>'


def fmt(value: Any) -> str:
    if value is None or value == "":
        return "--"
    if isinstance(value, float):
        return f"{value:.2f}"
    return escape(str(value))


def coverage_value(result: dict[str, Any], name: str) -> Any:
    """One coverage column: the total, else the metric family's effective, then raw, percent."""
    coverage = result.get("coverage", {})
    if name == "total":
        return coverage.get("total_percent")
    effective = coverage.get("effective_metrics") or {}
    raw = coverage.get("raw_metrics") or {}
    return effective.get(name, raw.get(name))
