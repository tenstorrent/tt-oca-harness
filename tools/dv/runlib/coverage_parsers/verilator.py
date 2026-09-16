# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Detailed parser for Verilator's textual coverage database."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..coverage_model import (
    CoverageDetails,
    CoverageObservation,
    stable_id,
    toggle_signal_observations,
)

VERILATOR_METRIC_MAP = {
    "line": "line",
    "toggle": "toggle",
    "branch": "branch",
    "expr": "expression",
    "expression": "expression",
    "user": "user",
    "covergroup": "functional",
    "functional": "functional",
}


def _metadata(value: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in value.split("\x01"):
        if "\x02" not in part:
            continue
        key, field_value = part.split("\x02", 1)
        if key:
            fields[key] = field_value
    return fields


def parse_verilator_details(
    *,
    dut: str,
    tool: str,
    target: str | None,
    build_fingerprint: str | None,
    merged: Path,
) -> CoverageDetails:
    observations: list[CoverageObservation] = []
    toggle_points: list[tuple[CoverageObservation, str]] = []
    warnings: list[str] = []
    if not merged.is_file():
        return CoverageDetails(
            dut=dut,
            tool=tool,
            target=target,
            build_fingerprint=build_fingerprint,
            details_available=False,
            warnings=[f"Verilator coverage database is missing: {merged}"],
        )

    text = merged.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        match = re.match(r"^C '(.*)'\s+(\d+)\s*$", line)
        if match is None:
            continue
        fields = _metadata(match.group(1))
        native_metric = fields.get("t", "unknown").lower()
        metric_family = VERILATOR_METRIC_MAP.get(native_metric)
        if metric_family is None:
            warnings.append(f"unsupported Verilator metric `{native_metric}`")
            continue
        count = int(match.group(2))
        source = fields.get("f")
        line_number = None
        try:
            line_number = int(fields["l"]) if fields.get("l") else None
        except ValueError:
            warnings.append(f"invalid Verilator line number `{fields.get('l')}`")
        native_locator = "|".join(f"{key}={fields[key]}" for key in sorted(fields))
        observation_id = stable_id(
            "VLTCOV",
            {
                "tool": tool,
                "metric": native_metric,
                "locator": native_locator,
            },
        )
        observation = CoverageObservation(
            id=observation_id,
            tool=tool,
            metric_family=metric_family,
            native_metric=native_metric,
            native_locator=native_locator,
            source=source,
            line=line_number,
            hierarchy=fields.get("h"),
            count=count,
            goal=1,
            covered=count > 0,
            category=metric_family,
        )
        observations.append(observation)
        if metric_family == "toggle":
            toggle_points.append((observation, fields.get("o", "")))

    observations.extend(toggle_signal_observations(toggle_points, id_prefix="VLTCOV"))

    details = CoverageDetails(
        dut=dut,
        tool=tool,
        target=target,
        build_fingerprint=build_fingerprint,
        details_available=bool(observations),
        observations_complete=True,
        observations=observations,
        warnings=sorted(set(warnings)),
    )
    scope_payload = "\n".join(
        sorted(
            f"{observation.metric_family}|{observation.source}|"
            f"{observation.hierarchy}|{observation.native_locator}"
            for observation in observations
        )
    )
    details.scope_fingerprint = hashlib.sha256(scope_payload.encode()).hexdigest()
    details.finalize()
    return details
