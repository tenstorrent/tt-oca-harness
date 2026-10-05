# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Detailed and scalar parsing for IMC/Xcelium coverage reports."""

from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path

from ..coverage_model import (
    CoverageDetails,
    CoverageObservation,
    MetricRecord,
    stable_id,
)

IMC_METRIC_MAP = {
    "line": "line",
    "statement": "line",
    "block": "line",
    "condition": "condition",
    "cond": "condition",
    "expression": "expression",
    "expr": "expression",
    "toggle": "toggle",
    "branch": "branch",
    "fsm": "fsm_state",
    "fsm_state": "fsm_state",
    "fsm_transition": "fsm_transition",
    "assertion": "assertion",
    "assert": "assertion",
    "covergroup": "functional",
    "group": "functional",
    "bin": "functional",
    "cross": "functional",
    "functional": "functional",
}


def _summary_metrics(paths: list[Path]) -> list[MetricRecord]:
    values: dict[str, tuple[str, float]] = {}
    pattern = re.compile(
        r"(?im)^\s*(line|statement|block|cond(?:ition)?|expr(?:ession)?|toggle|"
        r"branch|fsm(?:_state|_transition)?|assert(?:ion)?|covergroup|group|"
        r"functional)(?:\s+coverage)?\s*[:=]\s*(\d+(?:\.\d+)?)\s*%?"
    )
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            native = match.group(1).lower()
            family = IMC_METRIC_MAP[native]
            values.setdefault(family, (native, float(match.group(2))))
    return [
        MetricRecord(
            metric_family=family,
            native_metric=native,
            raw_percent=value,
            effective_percent=value,
        )
        for family, (native, value) in sorted(values.items())
    ]


def _fields(line: str) -> dict[str, str] | None:
    marker = "COVERAGE_HOLE"
    if marker not in line:
        return None
    values: dict[str, str] = {}
    for token in shlex.split(line.partition(marker)[2].strip()):
        key, separator, value = token.partition("=")
        if separator:
            values[key] = value
    return values if values.get("metric") else None


def _observation(
    fields: dict[str, str],
    *,
    tool: str,
) -> CoverageObservation | None:
    native_metric = fields.get("metric", "").lower()
    family = IMC_METRIC_MAP.get(native_metric)
    if family is None:
        return None
    try:
        count = int(fields.get("count", "0"))
        goal = int(fields.get("goal", "1"))
        line_number = int(fields["line"]) if fields.get("line") else None
    except ValueError:
        return None
    locator = fields.get("locator") or "|".join(f"{key}={fields[key]}" for key in sorted(fields))
    return CoverageObservation(
        id=stable_id(
            "IMCCOV",
            {"tool": tool, "metric": native_metric, "locator": locator},
        ),
        tool=tool,
        metric_family=family,
        native_metric=native_metric,
        native_locator=locator,
        source=fields.get("source"),
        line=line_number,
        hierarchy=fields.get("hierarchy"),
        count=count,
        goal=goal,
        covered=count >= goal,
        category=family,
    )


def _observations(paths: list[Path], tool: str) -> list[CoverageObservation]:
    output: list[CoverageObservation] = []
    seen: set[str] = set()
    simple = re.compile(
        r"(?i)\buncovered\s+(line|statement|block|cond(?:ition)?|expr(?:ession)?|"
        r"toggle|branch|fsm(?:_state|_transition)?|assert(?:ion)?|covergroup|"
        r"group|bin|cross|functional)\b.*?\b([A-Za-z0-9_./-]+\.s?vh?)"
        r"(?::(\d+))?"
    )
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            parsed = _fields(line)
            observation = _observation(parsed, tool=tool) if parsed else None
            if observation is None:
                match = simple.search(line)
                if match:
                    observation = _observation(
                        {
                            "metric": match.group(1).lower(),
                            "source": match.group(2),
                            "line": match.group(3) or "",
                            "locator": line.strip(),
                        },
                        tool=tool,
                    )
            if observation is not None and observation.id not in seen:
                seen.add(observation.id)
                output.append(observation)
    return output


def parse_imc_details(
    *,
    dut: str,
    tool: str,
    target: str | None,
    build_fingerprint: str | None,
    report_dir: Path,
    log_path: Path | None,
) -> CoverageDetails:
    report_paths: list[Path] = []
    detail_paths: list[Path] = []
    if report_dir.is_dir():
        report_paths.extend(report_dir.rglob("*.txt"))
        detail_paths = [path for path in report_paths if "detail" in path.name.lower()]
    if log_path is not None and log_path.is_file():
        report_paths.append(log_path)
    report_paths = sorted(set(report_paths))
    observations = _observations(detail_paths, tool)
    details_available = bool(detail_paths) and any(
        "COVERAGE_HOLE" in path.read_text(encoding="utf-8", errors="replace")
        or re.search(
            r"(?i)\b(uncovered|imc)\b",
            path.read_text(encoding="utf-8", errors="replace"),
        )
        for path in detail_paths
    )
    warnings: list[str] = []
    if not report_paths:
        warnings.append("IMC report files were not found")
    elif not details_available:
        warnings.append("IMC scalar summary found, but detailed hole files are unavailable")
    details = CoverageDetails(
        dut=dut,
        tool=tool,
        target=target,
        build_fingerprint=build_fingerprint,
        details_available=details_available,
        observations_complete=False,
        metrics=_summary_metrics(report_paths),
        observations=observations,
        warnings=warnings,
    )
    scope_payload = "\n".join(
        f"{path}:{hashlib.sha256(path.read_bytes()).hexdigest()}" for path in detail_paths
    )
    details.scope_fingerprint = hashlib.sha256(scope_payload.encode()).hexdigest()
    details.finalize()
    return details
