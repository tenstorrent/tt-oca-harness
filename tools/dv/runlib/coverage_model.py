# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Tool-neutral coverage closure records and aggregate helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

DETAILS_SCHEMA_VERSION = 1
CLOSURE_METRICS = (
    "line",
    "condition",
    "toggle",
    "branch",
    "fsm_state",
    "fsm_transition",
    "assertion",
    "functional",
    "expression",
    "user",
)


def percentage(covered: int | None, total: int | None) -> float | None:
    if covered is None or total is None or total <= 0:
        return None
    return round(100.0 * covered / total, 4)


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:16]}"


def coverage_comparison_key(
    *,
    dut: str,
    tool: str,
    target: str | None,
    scope_fingerprint: str | None,
    policy_fingerprint: str | None,
) -> str:
    return stable_id(
        "COVCMP",
        {
            "dut": dut,
            "tool": tool,
            "target": target,
            "scope_fingerprint": scope_fingerprint,
            "policy_fingerprint": policy_fingerprint,
        },
    )


@dataclass
class MetricRecord:
    metric_family: str
    native_metric: str
    available: bool = True
    covered: int | None = None
    total: int | None = None
    excluded: int = 0
    raw_percent: float | None = None
    effective_percent: float | None = None

    def finalize(self) -> None:
        if self.raw_percent is None:
            self.raw_percent = percentage(self.covered, self.total)
        if self.effective_percent is None:
            effective_total = (
                max((self.total or 0) - self.excluded, 0) if self.total is not None else None
            )
            self.effective_percent = percentage(self.covered, effective_total)

    def to_dict(self) -> dict[str, Any]:
        self.finalize()
        return asdict(self)


@dataclass
class CoverageObservation:
    id: str
    tool: str
    metric_family: str
    native_metric: str
    native_locator: str
    count: int
    goal: int = 1
    source: str | None = None
    line: int | None = None
    hierarchy: str | None = None
    category: str = "unclassified"
    covered: bool = False
    disposition: str = "cover"
    status: str = "open"
    confidence: str = "unclassified"
    policy_id: str | None = None
    rationale: str | None = None
    owner: str | None = None
    reviewer: str | None = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageDetails:
    dut: str
    tool: str
    target: str | None
    build_fingerprint: str | None
    details_available: bool
    observations_complete: bool = False
    metrics: list[MetricRecord] = field(default_factory=list)
    observations: list[CoverageObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_fingerprint: str | None = None
    scope_fingerprint: str | None = None
    comparison_key: str | None = None
    thresholds: list[dict[str, Any]] = field(default_factory=list)
    policy_application: dict[str, Any] = field(default_factory=dict)
    schema_version: int = DETAILS_SCHEMA_VERSION

    def finalize(self) -> None:
        if self.observations and self.observations_complete:
            self.metrics = metrics_from_observations(self.observations)
        else:
            for metric in self.metrics:
                metric.finalize()
        self.comparison_key = coverage_comparison_key(
            dut=self.dut,
            tool=self.tool,
            target=self.target,
            scope_fingerprint=self.scope_fingerprint,
            policy_fingerprint=self.policy_fingerprint,
        )

    def holes(self) -> list[CoverageObservation]:
        return [observation for observation in self.observations if not observation.covered]

    def holes_summary(self, sample_limit: int = 100) -> dict[str, Any]:
        holes = self.holes()
        by_metric: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_disposition: dict[str, int] = {}
        by_status: dict[str, int] = {}
        logical_ids: set[str] = set()
        for hole in holes:
            by_metric[hole.metric_family] = by_metric.get(hole.metric_family, 0) + 1
            by_category[hole.category] = by_category.get(hole.category, 0) + 1
            by_disposition[hole.disposition] = by_disposition.get(hole.disposition, 0) + 1
            by_status[hole.status] = by_status.get(hole.status, 0) + 1
            if hole.policy_id:
                logical_ids.add(hole.policy_id)
        return {
            "details_available": self.details_available,
            "observations_complete": self.observations_complete,
            "native_point_count": len(holes),
            "hole_group_count": len(logical_ids),
            "open": sum(1 for hole in holes if hole.status == "open"),
            "accepted": sum(1 for hole in holes if hole.status == "accepted"),
            "unclassified": sum(1 for hole in holes if not hole.policy_id),
            "by_metric": dict(sorted(by_metric.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_disposition": dict(sorted(by_disposition.items())),
            "by_status": dict(sorted(by_status.items())),
            "samples": [hole.to_dict() for hole in holes[:sample_limit]],
            "sample_truncated": len(holes) > sample_limit,
        }

    def to_dict(self) -> dict[str, Any]:
        self.finalize()
        return {
            "schema_version": self.schema_version,
            "dut": self.dut,
            "tool": self.tool,
            "target": self.target,
            "build_fingerprint": self.build_fingerprint,
            "details_available": self.details_available,
            "scope_fingerprint": self.scope_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "comparison_key": self.comparison_key,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "observations": [observation.to_dict() for observation in self.observations],
            "holes_summary": self.holes_summary(),
            "thresholds": self.thresholds,
            "policy_application": self.policy_application,
            "warnings": self.warnings,
        }


def metrics_from_observations(
    observations: list[CoverageObservation],
) -> list[MetricRecord]:
    groups: dict[tuple[str, str], list[CoverageObservation]] = {}
    for observation in observations:
        groups.setdefault((observation.metric_family, observation.native_metric), []).append(
            observation
        )

    records: list[MetricRecord] = []
    for (metric_family, native_metric), points in sorted(groups.items()):
        covered = sum(1 for point in points if point.covered)
        excluded = sum(
            1
            for point in points
            if not point.covered
            and point.status == "accepted"
            and point.disposition in {"waive", "exclude_scope"}
        )
        effective_total = len(points) - excluded
        records.append(
            MetricRecord(
                metric_family=metric_family,
                native_metric=native_metric,
                covered=covered,
                total=len(points),
                excluded=excluded,
                raw_percent=percentage(covered, len(points)),
                effective_percent=percentage(covered, effective_total),
            )
        )
    return records
