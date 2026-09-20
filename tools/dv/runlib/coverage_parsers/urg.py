# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Detailed and scalar parsing for URG/VCS coverage reports."""

from __future__ import annotations

import hashlib
import html
import re
import shlex
from pathlib import Path

from ..coverage import parse_urg_summary_table
from ..coverage_model import (
    CoverageDetails,
    CoverageObservation,
    MetricRecord,
    stable_id,
)

URG_METRIC_MAP = {
    "line": "line",
    "cond": "condition",
    "condition": "condition",
    "toggle": "toggle",
    "tgl": "toggle",
    "branch": "branch",
    "fsm": "fsm_state",
    "fsm_state": "fsm_state",
    "fsm_transition": "fsm_transition",
    "assert": "assertion",
    "assertion": "assertion",
    "group": "functional",
    "functional": "functional",
}
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?")


def _text(path: Path) -> str:
    value = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
    return value


def _summary_metrics(paths: list[Path]) -> list[MetricRecord]:
    values: dict[str, tuple[str, float]] = {}
    # Prefer the dashboard's `Total Coverage Summary`: it is the only URG
    # table guaranteed to hold pure percentages, whereas the loose scan below
    # can mistake covered/total counts in other report files for percentages.
    for path in paths:
        if path.name.lower() != "dashboard.txt":
            continue
        for native, value in parse_urg_summary_table(_text(path)).items():
            family = URG_METRIC_MAP.get(native)
            if family:
                values.setdefault(family, (native, value))
    if values:
        return [
            MetricRecord(
                metric_family=family,
                native_metric=native,
                raw_percent=value,
                effective_percent=value,
            )
            for family, (native, value) in sorted(values.items())
        ]
    for path in paths:
        text = _text(path)
        for match in re.finditer(
            r"(?im)^\s*(line|cond(?:ition)?|toggle|tgl|branch|fsm|assert(?:ion)?|"
            r"group|functional)(?:\s+coverage)?\s*[:=]\s*(\d+(?:\.\d+)?)\s*%?",
            text,
        ):
            native = match.group(1).lower()
            values.setdefault(
                URG_METRIC_MAP[native],
                (native, float(match.group(2))),
            )
        lines = text.splitlines()
        for index, line in enumerate(lines[:-1]):
            headers = [token.lower() for token in re.findall(r"[A-Za-z_]+", line)]
            recognized = [token for token in headers if token in URG_METRIC_MAP]
            if len(recognized) < 2:
                continue
            numbers = [float(value) for value in PERCENT_RE.findall(lines[index + 1])]
            if len(numbers) < len(headers):
                continue
            for native, value in zip(headers, numbers, strict=False):
                family = URG_METRIC_MAP.get(native)
                if family:
                    values.setdefault(family, (native, value))
    return [
        MetricRecord(
            metric_family=family,
            native_metric=native,
            raw_percent=value,
            effective_percent=value,
        )
        for family, (native, value) in sorted(values.items())
    ]


def _kv_hole(line: str) -> dict[str, str] | None:
    if "COVERAGE_HOLE" not in line:
        return None
    fields: dict[str, str] = {}
    for token in shlex.split(line.partition("COVERAGE_HOLE")[2].strip()):
        key, separator, value = token.partition("=")
        if separator:
            fields[key] = value
    return fields if fields.get("metric") else None


def _observation_from_fields(
    fields: dict[str, str],
    *,
    tool: str,
) -> CoverageObservation | None:
    native_metric = fields.get("metric", "").lower()
    metric_family = URG_METRIC_MAP.get(native_metric)
    if metric_family is None:
        return None
    try:
        count = int(fields.get("count", "0"))
        goal = int(fields.get("goal", "1"))
        line_number = int(fields["line"]) if fields.get("line") else None
    except ValueError:
        return None
    native_locator = fields.get("locator") or "|".join(
        f"{key}={fields[key]}" for key in sorted(fields)
    )
    return CoverageObservation(
        id=stable_id(
            "URGCOV",
            {
                "tool": tool,
                "metric": native_metric,
                "locator": native_locator,
            },
        ),
        tool=tool,
        metric_family=metric_family,
        native_metric=native_metric,
        native_locator=native_locator,
        source=fields.get("source"),
        line=line_number,
        hierarchy=fields.get("hierarchy"),
        count=count,
        goal=goal,
        covered=count >= goal,
        category=metric_family,
    )


def _hole_observations(paths: list[Path], tool: str) -> list[CoverageObservation]:
    observations: list[CoverageObservation] = []
    seen: set[str] = set()
    simple = re.compile(
        r"(?i)\buncovered\s+(line|cond(?:ition)?|toggle|tgl|branch|fsm|"
        r"assert(?:ion)?|group|functional)\b.*?\b([A-Za-z0-9_./-]+\.s?vh?)"
        r"(?::(\d+))?"
    )
    for path in paths:
        for line in _text(path).splitlines():
            fields = _kv_hole(line)
            observation = (
                _observation_from_fields(fields, tool=tool) if fields is not None else None
            )
            if observation is None:
                match = simple.search(line)
                if match:
                    native = match.group(1).lower()
                    source = match.group(2)
                    line_number = int(match.group(3)) if match.group(3) else None
                    locator = line.strip()
                    observation = _observation_from_fields(
                        {
                            "metric": native,
                            "source": source,
                            "line": str(line_number or ""),
                            "locator": locator,
                        },
                        tool=tool,
                    )
            if observation is not None and observation.id not in seen:
                seen.add(observation.id)
                observations.append(observation)
    return observations


def _report_files(report_dir: Path) -> list[Path]:
    paths: list[Path] = []
    if report_dir.is_dir():
        for pattern in ("*.txt", "*.html", "*.htm"):
            paths.extend(report_dir.rglob(pattern))
    return sorted(set(paths))


def _apply_raw_report(metrics: list[MetricRecord], raw_report_dir: Path | None) -> list[str]:
    """Take each family's raw percentage from the report URG wrote without exclusions.

    URG applies an exclusion file while it reports, so one report carries either the raw or
    the effective figure. The graded report is the effective one; the raw report exists only
    when the report stage ran with exclusion inputs.
    """
    if raw_report_dir is None:
        return []
    raw_paths = _report_files(raw_report_dir)
    if not raw_paths:
        return [f"raw URG report files were not found under {raw_report_dir}"]
    raw_values = {
        record.metric_family: record.raw_percent for record in _summary_metrics(raw_paths)
    }
    for record in metrics:
        if record.metric_family in raw_values:
            record.raw_percent = raw_values[record.metric_family]
    return []


def parse_urg_details(
    *,
    dut: str,
    tool: str,
    target: str | None,
    build_fingerprint: str | None,
    report_dir: Path,
    log_path: Path | None,
    raw_report_dir: Path | None = None,
) -> CoverageDetails:
    report_paths: list[Path] = []
    detail_paths: list[Path] = []
    if report_dir.is_dir():
        for pattern in ("*.txt", "*.html", "*.htm"):
            report_paths.extend(report_dir.rglob(pattern))
        detail_paths = [
            path for path in report_paths if path.name not in {"dashboard.txt", "dashboard.html"}
        ]
    if log_path is not None and log_path.is_file():
        report_paths.append(log_path)
    report_paths = sorted(set(report_paths))
    observations = _hole_observations(detail_paths, tool)
    details_available = bool(detail_paths) and any(
        "COVERAGE_HOLE" in _text(path) or re.search(r"(?i)\b(uncovered|urg)\b", _text(path))
        for path in detail_paths
    )
    warnings: list[str] = []
    if not report_paths:
        warnings.append("URG report files were not found")
    elif not details_available:
        warnings.append("URG scalar summary found, but detailed hole files are unavailable")
    metrics = _summary_metrics(report_paths)
    warnings.extend(_apply_raw_report(metrics, raw_report_dir))
    details = CoverageDetails(
        dut=dut,
        tool=tool,
        target=target,
        build_fingerprint=build_fingerprint,
        details_available=details_available,
        observations_complete=False,
        metrics=metrics,
        observations=observations,
        warnings=warnings,
    )
    scope_payload = "\n".join(
        f"{path}:{hashlib.sha256(path.read_bytes()).hexdigest()}" for path in detail_paths
    )
    details.scope_fingerprint = hashlib.sha256(scope_payload.encode()).hexdigest()
    details.finalize()
    return details
