# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Checked-in coverage closure policy loading, validation, and application."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date as calendar_date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import load_toml
from .coverage_model import CoverageDetails, CoverageObservation, percentage
from .models import ConfigError

POLICY_SCHEMA_VERSION = 1
ALLOWED_CATEGORIES = {
    "missing_test",
    "missing_stimulus",
    "coverage_model_gap",
    "design_bug",
    "unreachable",
    "tied_off",
    "config_disabled",
    "out_of_scope",
    "third_party",
    "statistical",
    "tool_artifact",
    "needs_review",
}
ALLOWED_DISPOSITIONS = {
    "cover",
    "waive",
    "exclude_scope",
    "fix_design",
    "fix_model",
    "review",
}
ALLOWED_STATUSES = {"open", "accepted", "closed", "obsolete"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ACTIONABLE_DISPOSITIONS = {"cover", "fix_design", "fix_model", "review"}
SELECTOR_FIELDS = {
    "tool",
    "metric_family",
    "native_metric",
    "native_locator",
    "source",
    "line",
    "hierarchy",
}
GITHUB_ISSUE_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*$"
)
NATIVE_FILE_KEYS = {"tool", "role", "path", "apply_phase", "args", "sha256"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ThresholdRule:
    id: str
    tool: str
    target: str
    scope: str
    metric_family: str
    population: str
    minimum_percent: float
    max_unclassified_points: int | None = None


@dataclass(frozen=True)
class NativePolicyFile:
    tool: str
    role: str
    path: Path
    apply_phase: str
    args: list[str]
    sha256: str


@dataclass(frozen=True)
class HoleRule:
    id: str
    title: str
    category: str
    disposition: str
    status: str
    confidence: str
    rationale: str
    owner: str
    reviewer: str
    date: str
    expires: str | None
    issues: list[str]
    expected_matches: int
    selectors: list[dict[str, Any]]
    expired: bool = False


@dataclass
class CoveragePolicy:
    path: Path
    dut: str
    scope_epoch: str
    thresholds: list[ThresholdRule] = field(default_factory=list)
    native_files: list[NativePolicyFile] = field(default_factory=list)
    holes: list[HoleRule] = field(default_factory=list)
    sha256: str = ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_table_list(value: Any, where: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigError(f"{where} must be an array of tables")
    return list(value)


def _required_string(table: dict[str, Any], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(table: dict[str, Any], key: str, where: str) -> str | None:
    value = table.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where}.{key} must be a string")
    return value.strip()


def _string_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where} must be a list of strings")
    return list(value)


def _validate_issue_urls(values: list[str], where: str) -> None:
    for value in values:
        if not GITHUB_ISSUE_RE.fullmatch(value):
            raise ConfigError(f"{where} must contain full GitHub issue URLs, got `{value}`")


def safe_issue_url(value: str) -> bool:
    if not GITHUB_ISSUE_RE.fullmatch(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.netloc == "github.com"


def _load_thresholds(data: dict[str, Any], path: Path) -> list[ThresholdRule]:
    rules: list[ThresholdRule] = []
    seen: set[str] = set()
    for index, table in enumerate(_as_table_list(data.get("thresholds"), "thresholds")):
        where = f"{path} [[thresholds]] #{index + 1}"
        rule_id = _required_string(table, "id", where)
        if rule_id in seen:
            raise ConfigError(f"{where}: duplicate threshold id `{rule_id}`")
        seen.add(rule_id)
        try:
            minimum = float(table.get("minimum_percent"))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{where}.minimum_percent must be a number") from exc
        if minimum < 0.0 or minimum > 100.0:
            raise ConfigError(f"{where}.minimum_percent must be between 0 and 100")
        population = str(table.get("population", "effective"))
        if population not in {"raw", "effective"}:
            raise ConfigError(f"{where}.population must be `raw` or `effective`")
        maximum = table.get("max_unclassified_points")
        if maximum is not None and (
            not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0
        ):
            raise ConfigError(f"{where}.max_unclassified_points must be >= 0")
        rules.append(
            ThresholdRule(
                id=rule_id,
                tool=str(table.get("tool", "*")),
                target=str(table.get("target", "*")),
                scope=str(table.get("scope", "*")),
                metric_family=_required_string(table, "metric_family", where),
                population=population,
                minimum_percent=minimum,
                max_unclassified_points=maximum,
            )
        )
    return rules


def _load_native_files(
    data: dict[str, Any],
    policy_path: Path,
) -> list[NativePolicyFile]:
    files: list[NativePolicyFile] = []
    for index, table in enumerate(_as_table_list(data.get("native_files"), "native_files")):
        where = f"{policy_path} [[native_files]] #{index + 1}"
        unknown = sorted(set(table) - NATIVE_FILE_KEYS)
        if unknown:
            raise ConfigError(f"{where}: unsupported key(s): {', '.join(unknown)}")
        raw_path = Path(_required_string(table, "path", where)).expanduser()
        resolved = raw_path if raw_path.is_absolute() else policy_path.parent / raw_path
        if not resolved.is_file():
            raise ConfigError(f"{where}: native policy file does not exist: {resolved}")
        phase = str(table.get("apply_phase", "report"))
        if phase not in {"merge", "report"}:
            raise ConfigError(f"{where}.apply_phase must be `merge` or `report`")
        args = _string_list(table.get("args"), f"{where}.args")
        if args and not any("{path}" in value for value in args):
            raise ConfigError(f"{where}.args must reference `{{path}}`")
        digest = _sha256(resolved)
        # A recorded digest pins the reviewed file: a regenerated file takes a new review.
        pinned = _optional_string(table, "sha256", where)
        if pinned is not None:
            if not SHA256_RE.fullmatch(pinned):
                raise ConfigError(f"{where}.sha256 must be 64 lowercase hexadecimal digits")
            if pinned != digest:
                raise ConfigError(
                    f"{where}.sha256 does not match {resolved}: recorded {pinned}, file {digest}"
                )
        files.append(
            NativePolicyFile(
                tool=_required_string(table, "tool", where),
                role=_required_string(table, "role", where),
                path=resolved.resolve(),
                apply_phase=phase,
                args=args,
                sha256=digest,
            )
        )
    return files


def _load_holes(data: dict[str, Any], path: Path) -> list[HoleRule]:
    holes: list[HoleRule] = []
    seen: set[str] = set()
    for index, table in enumerate(_as_table_list(data.get("holes"), "holes")):
        where = f"{path} [[holes]] #{index + 1}"
        hole_id = _required_string(table, "id", where)
        if hole_id in seen:
            raise ConfigError(f"{where}: duplicate hole id `{hole_id}`")
        seen.add(hole_id)
        category = _required_string(table, "category", where)
        disposition = _required_string(table, "disposition", where)
        status = _required_string(table, "status", where)
        confidence = _required_string(table, "confidence", where)
        if category not in ALLOWED_CATEGORIES:
            raise ConfigError(f"{where}.category is unsupported: {category}")
        if disposition not in ALLOWED_DISPOSITIONS:
            raise ConfigError(f"{where}.disposition is unsupported: {disposition}")
        if status not in ALLOWED_STATUSES:
            raise ConfigError(f"{where}.status is unsupported: {status}")
        if confidence not in ALLOWED_CONFIDENCE:
            raise ConfigError(f"{where}.confidence is unsupported: {confidence}")
        rationale = _required_string(table, "rationale", where)
        owner = _required_string(table, "owner", where)
        reviewer = _required_string(table, "reviewer", where)
        date = _required_string(table, "date", where)
        expires = _optional_string(table, "expires", where)
        for field_name, date_value in (("date", date), ("expires", expires)):
            if date_value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
                raise ConfigError(f"{where}.{field_name} must use YYYY-MM-DD")
        expired = bool(
            status == "accepted"
            and expires
            and calendar_date.fromisoformat(expires) < calendar_date.today()
        )
        issues = _string_list(table.get("issues"), f"{where}.issues")
        _validate_issue_urls(issues, f"{where}.issues")
        if status == "open" and disposition in ACTIONABLE_DISPOSITIONS and not issues:
            raise ConfigError(
                f"{where}: actionable open hole `{hole_id}` requires a GitHub issue URL"
            )
        if (
            status == "accepted"
            and disposition in {"waive", "exclude_scope"}
            and confidence == "low"
        ):
            raise ConfigError(
                f"{where}: low-confidence holes cannot be accepted as waivers/exclusions"
            )
        expected = table.get("expected_matches", 1)
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            raise ConfigError(f"{where}.expected_matches must be a positive integer")
        selectors = _as_table_list(table.get("native"), f"{where}.native")
        if not selectors:
            raise ConfigError(f"{where}: at least one [[holes.native]] selector is required")
        for selector in selectors:
            unknown = sorted(set(selector) - SELECTOR_FIELDS)
            if unknown:
                raise ConfigError(f"{where}: unsupported selector key(s): {', '.join(unknown)}")
            if not selector:
                raise ConfigError(f"{where}: empty native selector is not allowed")
        holes.append(
            HoleRule(
                id=hole_id,
                title=_required_string(table, "title", where),
                category=category,
                disposition=disposition,
                status=status,
                confidence=confidence,
                rationale=rationale,
                owner=owner,
                reviewer=reviewer,
                date=date,
                expires=expires,
                issues=issues,
                expected_matches=expected,
                selectors=selectors,
                expired=expired,
            )
        )
    return holes


def load_coverage_policy(
    path: Path,
    *,
    expected_dut: str,
) -> CoveragePolicy:
    data = load_toml(path)
    if int(data.get("schema_version", 0)) != POLICY_SCHEMA_VERSION:
        raise ConfigError(f"{path}: schema_version must be {POLICY_SCHEMA_VERSION}")
    dut = _required_string(data, "dut", str(path))
    if dut != expected_dut:
        raise ConfigError(f"{path}: policy DUT `{dut}` does not match `{expected_dut}`")
    return CoveragePolicy(
        path=path.resolve(),
        dut=dut,
        scope_epoch=str(data.get("scope_epoch", "default")),
        thresholds=_load_thresholds(data, path),
        native_files=_load_native_files(data, path),
        holes=_load_holes(data, path),
        sha256=_sha256(path),
    )


def native_policy_args(
    policy: CoveragePolicy | None,
    *,
    tool: str,
    phase: str,
) -> list[str]:
    argv: list[str] = []
    if policy is None:
        return argv
    for entry in policy.native_files:
        if entry.tool not in {tool, "*"} or entry.apply_phase != phase:
            continue
        argv.extend(value.replace("{path}", str(entry.path)) for value in entry.args)
    return argv


def native_policy_manifest(policy: CoveragePolicy | None) -> list[dict[str, Any]]:
    if policy is None:
        return []
    return [
        {
            "tool": entry.tool,
            "role": entry.role,
            "path": str(entry.path),
            "apply_phase": entry.apply_phase,
            "sha256": entry.sha256,
        }
        for entry in policy.native_files
    ]


def expired_holes(policy: CoveragePolicy | None) -> list[HoleRule]:
    if policy is None:
        return []
    return [rule for rule in policy.holes if rule.expired]


def lapsed_warning(rule: HoleRule) -> str:
    return f"{rule.id} expired on {rule.expires}; treated as open"


def _selector_matches(
    observation: CoverageObservation,
    selector: dict[str, Any],
) -> bool:
    for key, expected in selector.items():
        actual = getattr(observation, key)
        if key == "line":
            try:
                if actual != int(expected):
                    return False
            except (TypeError, ValueError):
                return False
            continue
        if not fnmatch.fnmatchcase(str(actual or ""), str(expected)):
            return False
    return True


def apply_coverage_policy(
    details: CoverageDetails,
    policy: CoveragePolicy | None,
) -> CoverageDetails:
    application: dict[str, Any] = {
        "policy": str(policy.path) if policy else None,
        "policy_sha256": policy.sha256 if policy else None,
        "native_files": native_policy_manifest(policy),
        "matched": [],
        "warnings": [],
    }
    if policy is None:
        details.policy_application = application
        details.finalize()
        return details

    claimed: dict[str, str] = {}
    lapsed: list[str] = []
    for rule in policy.holes:
        matches = [
            observation
            for observation in details.observations
            if any(_selector_matches(observation, selector) for selector in rule.selectors)
        ]
        if len(matches) != rule.expected_matches:
            raise ConfigError(
                f"{policy.path}: hole `{rule.id}` matched {len(matches)} observation(s), "
                f"expected {rule.expected_matches}"
            )
        # An accepted waiver past its `expires` date grades as open; the observation keeps
        # the rule's identity and disposition.
        status = "open" if rule.expired else rule.status
        if (
            status == "accepted"
            and rule.disposition in {"waive", "exclude_scope"}
            and any(observation.covered for observation in matches)
        ):
            raise ConfigError(
                f"{policy.path}: accepted selector `{rule.id}` unexpectedly matched a covered point"
            )
        for observation in matches:
            if observation.id in claimed:
                raise ConfigError(
                    f"{policy.path}: observation `{observation.id}` is claimed by both "
                    f"`{claimed[observation.id]}` and `{rule.id}`"
                )
            claimed[observation.id] = rule.id
            observation.policy_id = rule.id
            observation.category = rule.category
            observation.disposition = rule.disposition
            observation.status = status
            observation.confidence = rule.confidence
            observation.rationale = rule.rationale
            observation.owner = rule.owner
            observation.reviewer = rule.reviewer
            observation.issues = list(rule.issues)
        if rule.expired:
            lapsed.append(lapsed_warning(rule))
        application["matched"].append(
            {
                "policy_id": rule.id,
                "observation_ids": [observation.id for observation in matches],
            }
        )
    if lapsed:
        application["warnings"] = [*application["warnings"], *lapsed]
        details.warnings = [*details.warnings, *lapsed]

    details.policy_fingerprint = policy.sha256
    details.scope_fingerprint = hashlib.sha256(
        (
            f"{details.build_fingerprint or ''}\0"
            f"{details.scope_fingerprint or ''}\0{policy.scope_epoch}"
        ).encode()
    ).hexdigest()
    details.finalize()
    details.thresholds = evaluate_thresholds(details, policy)
    details.policy_application = application
    return details


def evaluate_thresholds(
    details: CoverageDetails,
    policy: CoveragePolicy,
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for rule in policy.thresholds:
        if rule.tool not in {"*", details.tool}:
            continue
        if rule.target not in {"*", str(details.target or "")}:
            continue
        scoped_observations = [
            observation
            for observation in details.observations
            if observation.metric_family == rule.metric_family
            and fnmatch.fnmatchcase(str(observation.hierarchy or ""), rule.scope)
        ]
        if rule.scope != "*":
            if details.observations_complete and scoped_observations:
                covered = sum(1 for observation in scoped_observations if observation.covered)
                excluded = sum(
                    1
                    for observation in scoped_observations
                    if not observation.covered
                    and observation.status == "accepted"
                    and observation.disposition in {"waive", "exclude_scope"}
                )
                total = len(scoped_observations)
                percent = percentage(
                    covered,
                    total if rule.population == "raw" else total - excluded,
                )
            else:
                percent = None
        else:
            records = [
                metric for metric in details.metrics if metric.metric_family == rule.metric_family
            ]
            percent_values = [
                (metric.raw_percent if rule.population == "raw" else metric.effective_percent)
                for metric in records
            ]
            available = [value for value in percent_values if value is not None]
            percent = min(available) if available else None
        unclassified = sum(
            1
            for hole in details.holes()
            if hole.metric_family == rule.metric_family
            and fnmatch.fnmatchcase(str(hole.hierarchy or ""), rule.scope)
            and not hole.policy_id
        )
        percent_met = percent is not None and percent >= rule.minimum_percent
        unclassified_met = (
            True
            if rule.max_unclassified_points is None
            else unclassified <= rule.max_unclassified_points
        )
        outcomes.append(
            {
                "id": rule.id,
                "metric_family": rule.metric_family,
                "population": rule.population,
                "scope": rule.scope,
                "minimum_percent": rule.minimum_percent,
                "actual_percent": percent,
                "max_unclassified_points": rule.max_unclassified_points,
                "unclassified_points": unclassified,
                "met": percent_met and unclassified_met,
            }
        )
    return outcomes
