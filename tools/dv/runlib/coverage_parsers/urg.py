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
    percentage,
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
    # urg has no user family. The `cover property` statements the cov/sv
    # modules declare through OCAH_FCOV_COVER are what Verilator reports as
    # `user`, and urg reads them under its assert metric together with the
    # `assert property` statements; `asserts.txt` is the only place it splits
    # the two. The cover-property half is reported here as `user` so the same
    # policy family grades the same points on both simulators.
    "cover_property": "user",
    "user": "user",
}
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?")
COVER_SUMMARY_TITLE_RE = re.compile(r"^\s*Summary for Cover Properties\s*$")
COVER_SUMMARY_ROW_RE = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?)\s+(\d+)\s+\d+(?:\.\d+)?\s*$")
COVER_DETAIL_TITLE_RE = re.compile(r"^\s*Detail Report for Cover Properties\s*$")
COVER_DETAIL_ROW_RE = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")


def _text(path: Path) -> str:
    value = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
    return value


def _cover_property_summary(paths: list[Path]) -> MetricRecord | None:
    """The `Summary for Cover Properties` block of asserts.txt as one `user` record.

    urg prints the block as `<label> <count> <percent>` rows: `Total Number`,
    `Uncovered`, `Matches` and, when an exclusion file dropped properties,
    `Excluded`. Matches over the non-excluded population is the effective
    figure; over the whole population it is the raw one, which the raw report
    (written without exclusions) supersedes when the report stage kept one.
    """
    for path in paths:
        if path.name.lower() != "asserts.txt":
            continue
        lines = _text(path).splitlines()
        for index, line in enumerate(lines):
            if not COVER_SUMMARY_TITLE_RE.match(line):
                continue
            rows: dict[str, int] = {}
            for row in lines[index + 1 : index + 10]:
                match = COVER_SUMMARY_ROW_RE.match(row)
                if match:
                    rows[match.group(1).strip().lower()] = int(match.group(2))
                elif rows and not row.strip():
                    break
            total = rows.get("total number")
            covered = rows.get("matches")
            if total is None or covered is None:
                return None
            excluded = rows.get("excluded", 0)
            record = MetricRecord(
                metric_family="user",
                native_metric="cover_property",
                covered=covered,
                total=total,
                excluded=excluded,
                raw_percent=percentage(covered, total),
                effective_percent=percentage(covered, total - excluded),
            )
            return record
    return None


def _cover_property_observations(paths: list[Path], tool: str) -> list[CoverageObservation]:
    """One observation per row of asserts.txt's `Detail Report for Cover Properties`.

    The rows carry the property's full hierarchical name and its match count, so
    a policy `[[holes]]` entry can select an unhit point by `hierarchy` exactly as
    it does on the Verilator database.
    """
    observations: list[CoverageObservation] = []
    for path in paths:
        if path.name.lower() != "asserts.txt":
            continue
        in_detail = False
        for line in _text(path).splitlines():
            if COVER_DETAIL_TITLE_RE.match(line):
                in_detail = True
                continue
            if not in_detail:
                continue
            if re.match(r"^\s*Detail Report for ", line):
                break
            match = COVER_DETAIL_ROW_RE.match(line)
            if match is None or match.group(1).upper() == "COVER":
                continue
            hierarchy = match.group(1)
            matches = int(match.group(5))
            observations.append(
                CoverageObservation(
                    id=stable_id(
                        "URGCOV",
                        {"tool": tool, "metric": "cover_property", "locator": hierarchy},
                    ),
                    tool=tool,
                    metric_family="user",
                    native_metric="cover_property",
                    native_locator=hierarchy,
                    hierarchy=hierarchy,
                    count=matches,
                    goal=1,
                    covered=matches >= 1,
                    category="user",
                )
            )
        break
    return observations


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
    cover = _cover_property_summary(paths)
    if values:
        records = [
            MetricRecord(
                metric_family=family,
                native_metric=native,
                raw_percent=value,
                effective_percent=value,
            )
            for family, (native, value) in sorted(values.items())
        ]
        if cover is not None and "user" not in values:
            records.append(cover)
        return records
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
    records = [
        MetricRecord(
            metric_family=family,
            native_metric=native,
            raw_percent=value,
            effective_percent=value,
        )
        for family, (native, value) in sorted(values.items())
    ]
    if cover is not None and "user" not in values:
        records.append(cover)
    return records


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
    cover_observations = _cover_property_observations(detail_paths, tool)
    seen = {observation.id for observation in observations}
    observations.extend(o for o in cover_observations if o.id not in seen)
    details_available = bool(detail_paths) and (
        bool(cover_observations)
        or any(
            "COVERAGE_HOLE" in _text(path) or re.search(r"(?i)\b(uncovered|urg)\b", _text(path))
            for path in detail_paths
        )
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
