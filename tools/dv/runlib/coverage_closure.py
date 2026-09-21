# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Post-report coverage grading: parse, apply the policy, and write the graded files.

Every value that depends on the host (tool version, supported metrics,
compatibility threshold, policy) is a parameter, and every artifact path derives
from ``run_dir``; the caller owns the raw details payload taken before the policy
applies, and the vendor report command runs before any of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coverage import parse_coverage_report, write_json
from .coverage_model import CoverageDetails
from .coverage_parsers import parse_coverage_details
from .coverage_policy import CoveragePolicy, apply_coverage_policy
from .models import ConfigError
from .paths import repo_rel

SUMMARY_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CoverageRunPaths:
    """Coverage artifact locations of one run directory."""

    run_dir: Path
    cov_dir: Path
    merged: Path
    report_dir: Path
    raw_report_dir: Path
    manifest: Path
    summary: Path
    raw_details: Path
    details: Path
    application: Path


@dataclass
class ParsedCoverage:
    """Normalized report output before the policy applies."""

    scalar_metrics: dict[str, float]
    total_percent: float
    details: CoverageDetails


@dataclass(frozen=True)
class CoverageGrade:
    """Outcome of applying the policy and the thresholds to one parsed report."""

    status: str
    threshold: float
    total_percent: float
    compatibility_threshold_met: bool
    threshold_met: bool
    thresholds: list[dict[str, Any]]


def coverage_merged_name(tool: str, tool_cov: dict[str, Any]) -> str:
    merged_name = tool_cov.get("merged_name")
    if not isinstance(merged_name, str) or not merged_name:
        raise ConfigError(f"coverage.{tool}.merged_name must be a non-empty string")
    return merged_name


def coverage_parser_name(tool_cov: dict[str, Any]) -> str:
    return str(tool_cov.get("parser", ""))


def coverage_backend(tool: str, tool_cov: dict[str, Any]) -> str:
    return str(tool_cov.get("backend") or coverage_parser_name(tool_cov) or tool)


def coverage_fail_under(tool: str, tool_cov: dict[str, Any]) -> float | None:
    value = tool_cov.get("fail_under")
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"`coverage.{tool}.fail_under` must be a number") from exc


def coverage_run_paths(run_dir: Path, merged_name: str) -> CoverageRunPaths:
    cov_dir = run_dir / "cov"
    report_dir = cov_dir / "report"
    return CoverageRunPaths(
        run_dir=run_dir,
        cov_dir=cov_dir,
        merged=cov_dir / merged_name,
        report_dir=report_dir,
        raw_report_dir=cov_dir / "report_raw",
        manifest=cov_dir / "coverage.json",
        summary=report_dir / "summary.json",
        raw_details=report_dir / "coverage-details.raw.json",
        details=report_dir / "coverage-details.json",
        application=report_dir / "policy-application.json",
    )


def closure_scalar_metrics(details: CoverageDetails) -> dict[str, float]:
    aliases = {
        "condition": "cond",
        "fsm_state": "fsm",
        "fsm_transition": "fsm",
        "assertion": "assert",
    }
    metrics: dict[str, float] = {}
    for record in details.metrics:
        value = record.effective_percent
        if value is None:
            continue
        key = aliases.get(record.metric_family, record.metric_family)
        if key == "fsm" and key in metrics:
            metrics[key] = min(metrics[key], value)
        else:
            metrics[key] = value
    return metrics


def parse_coverage_run(
    *,
    parser: str,
    dut: str,
    tool: str,
    manifest: dict[str, Any],
    merged: Path,
    report_dir: Path,
    log_path: Path | None,
    raw_report_dir: Path | None = None,
) -> ParsedCoverage:
    """Normalize the vendor report into scalar metrics and closure details.

    ``raw_report_dir`` is the report the tool wrote without its exclusion inputs; when
    present, each metric family's raw percentage comes from it and the effective one from
    ``report_dir``.
    """

    scalar_metrics, total_percent = parse_coverage_report(
        parser=parser,
        report_dir=report_dir,
        merged=merged,
        log_path=log_path,
    )
    details = parse_coverage_details(
        parser=parser,
        dut=dut,
        tool=tool,
        target=manifest.get("target"),
        build_fingerprint=manifest.get("build_fingerprint"),
        report_dir=report_dir,
        merged=merged,
        log_path=log_path,
        raw_report_dir=raw_report_dir,
    )
    return ParsedCoverage(
        scalar_metrics=scalar_metrics,
        total_percent=total_percent,
        details=details,
    )


def grade_coverage_run(
    *,
    parsed: ParsedCoverage,
    manifest: dict[str, Any],
    dut: str,
    root: Path,
    tool: str,
    tool_cov: dict[str, Any],
    run_dir: Path,
    policy: CoveragePolicy | None,
    threshold: float,
    tool_version: str,
    supported_metrics: list[str],
) -> CoverageGrade:
    """Apply the policy and write the details, application, summary, and manifest.

    Every ``ConfigError`` the policy raises happens before the first write; the
    manifest's ``artifacts`` all point at the files under ``run_dir``.
    """

    paths = coverage_run_paths(run_dir, coverage_merged_name(tool, tool_cov))
    backend = coverage_backend(tool, tool_cov)
    details = apply_coverage_policy(parsed.details, policy)
    if details.policy_application.get("policy"):
        details.policy_application["policy"] = repo_rel(root, details.policy_application["policy"])
    for entry in details.policy_application.get("native_files", []):
        if isinstance(entry, dict) and entry.get("path"):
            entry["path"] = repo_rel(root, entry["path"])
    effective_details = details.to_dict()
    metrics = dict(parsed.scalar_metrics)
    metrics.update(closure_scalar_metrics(details))
    compatibility_threshold_met = parsed.total_percent >= threshold
    policy_threshold_met = all(bool(outcome.get("met")) for outcome in details.thresholds)
    threshold_met = compatibility_threshold_met and policy_threshold_met
    status = "PASS" if threshold_met else "FAIL"
    holes_summary = effective_details.get("holes_summary", {})
    summary_payload = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "dut": dut,
        "tool": tool,
        "backend": backend,
        "tool_versions": {tool: tool_version},
        "supported_metrics": supported_metrics,
        "metrics": metrics,
        "overall_percent": parsed.total_percent,
        "threshold": threshold,
        "threshold_met": threshold_met,
        "compatibility_threshold_met": compatibility_threshold_met,
        "policy_thresholds": details.thresholds,
        "status": status,
        "details_available": details.details_available,
        "comparison_key": details.comparison_key,
        "scope_fingerprint": details.scope_fingerprint,
        "policy_fingerprint": details.policy_fingerprint,
        "holes_summary": holes_summary,
        "inputs": [
            entry.get("path") for entry in manifest.get("inputs", []) if isinstance(entry, dict)
        ],
        "artifacts": {
            "merged": repo_rel(root, paths.merged),
            "report": repo_rel(root, paths.report_dir),
            "json": repo_rel(root, paths.summary),
            "manifest": repo_rel(root, paths.manifest),
            "coverage_details_raw": repo_rel(root, paths.raw_details),
            "coverage_details": repo_rel(root, paths.details),
            "policy_application": repo_rel(root, paths.application),
        },
    }
    manifest["status"] = status
    manifest["metrics"] = metrics
    manifest["overall_percent"] = parsed.total_percent
    manifest["threshold"] = threshold
    manifest["threshold_met"] = threshold_met
    manifest["policy_thresholds"] = details.thresholds
    manifest["comparison_key"] = details.comparison_key
    manifest["scope_fingerprint"] = details.scope_fingerprint
    manifest["policy_fingerprint"] = details.policy_fingerprint
    manifest["holes_summary"] = holes_summary
    manifest["report_return_code"] = 0
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        manifest["artifacts"] = artifacts
    artifacts["merged"] = repo_rel(root, paths.merged)
    artifacts["report"] = repo_rel(root, paths.report_dir)
    if paths.raw_report_dir.is_dir():
        artifacts["report_raw"] = repo_rel(root, paths.raw_report_dir)
    else:
        artifacts.pop("report_raw", None)
    artifacts["summary"] = repo_rel(root, paths.summary)
    artifacts["coverage_details_raw"] = repo_rel(root, paths.raw_details)
    artifacts["coverage_details"] = repo_rel(root, paths.details)
    artifacts["policy_application"] = repo_rel(root, paths.application)
    write_json(paths.details, effective_details)
    write_json(paths.application, details.policy_application)
    write_json(paths.summary, summary_payload)
    write_json(paths.manifest, manifest)
    return CoverageGrade(
        status=status,
        threshold=threshold,
        total_percent=parsed.total_percent,
        compatibility_threshold_met=compatibility_threshold_met,
        threshold_met=threshold_met,
        thresholds=details.thresholds,
    )
