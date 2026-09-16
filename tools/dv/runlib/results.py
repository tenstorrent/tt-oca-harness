# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Result aggregation and result.json generation."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .buildcache import binary_version
from .compat import UTC
from .formal import formal_summary
from .models import Flow, StageResult
from .paths import repo_rel
from .waves import WAVE_DEFAULT, same_seed_replay_command

# Tools whose version materially affects build/run reproducibility, with their version-query args.
TOOL_VERSION_ARGS = {
    "verilator": ["--version"],
    "vcs": ["-ID"],
    "xrun": ["-version"],
    "bender": ["--version"],
}

EXIT_CODE_BY_STATUS = {
    "PASS": 0,
    "FAIL": 1,
    "ERROR": 2,
    "TIMEOUT": 124,
    "UNKNOWN": 5,
}

NON_PASS_STATUSES = {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}

COVERAGE_BACKEND_BY_TOOL = {
    "verilator": "verilator_coverage",
    "vcs": "urg",
    "xcelium": "imc",
}

SIGNOFF_COVERAGE_TOOLS = {"vcs", "xcelium"}


def command_text(argv: list[str], root: Path) -> str:
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip()


def git_info(root: Path) -> dict[str, str]:
    return {
        "commit": command_text(["git", "rev-parse", "HEAD"], root),
        "branch": command_text(["git", "rev-parse", "--abbrev-ref", "HEAD"], root),
        "dirty": "true"
        if command_text(["git", "status", "--porcelain", "--untracked-files=no"], root)
        else "false",
    }


def tool_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version()}
    for tool, version_args in TOOL_VERSION_ARGS.items():
        if shutil.which(tool):
            versions[tool] = binary_version(tool, version_args, root)
    return versions


def primary_tool_version(tool: str, versions: dict[str, str]) -> str:
    version_key = "xrun" if tool == "xcelium" else tool
    return versions.get(version_key, "unknown")


def _site_layer_label(args: Any | None) -> str | None:
    """The site file the run applied (recorded on args by run_flow), or None."""
    if args is None:
        return None
    label = getattr(args, "_site_layer", None)
    return str(label) if label else None


def cli_overrides(args: Any | None) -> dict[str, Any]:
    if args is None:
        return {}
    out: dict[str, Any] = {}
    for key, value in vars(args).items():
        if key.startswith("_"):
            continue
        if value is None or value is False or value == []:
            continue
        if key in {"ui"} and value == "auto":
            continue
        if key in {"sim_jobs"} and value == 1:
            continue
        if key in {"mode"} and value == "sim":
            continue
        if key in {"retry"} and value == 0:
            continue
        out[key] = value
    return out


def aggregate_status(stages: list[StageResult]) -> str:
    statuses = [stage.status for stage in stages]
    if "ERROR" in statuses:
        return "ERROR"
    if "TIMEOUT" in statuses:
        return "TIMEOUT"
    if "FAIL" in statuses:
        return "FAIL"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "PASS"


def exit_code_for_status(status: str) -> int:
    return EXIT_CODE_BY_STATUS.get(status, 2)


def _stage_dict(stage: StageResult) -> dict[str, Any]:
    payload = {
        "name": stage.stage,
        "item": stage.item,
        "status": stage.status,
        "return_code": stage.return_code,
        "duration_sec": round(stage.duration_sec, 3),
        "started_at": stage.started_at,
        "ended_at": stage.ended_at,
        "log": stage.log,
        "artifacts": stage.artifacts or {},
        "failure_buckets": stage.failure_buckets or [],
        "reason": stage.reason,
        "parser": stage.parser,
        "metadata": stage.metadata or {},
    }
    if stage.target:
        payload["target"] = stage.target
    if stage.formal is not None:
        payload["formal"] = stage.formal
    return payload


# One executed formal item counts as one test item, beside the simulation leaves.
ITEM_STAGES = {"sim", "regress", "formal"}


def _has_formal(flow: Flow, stages: list[StageResult]) -> bool:
    return flow.framework == "formal" or any(stage.formal is not None for stage in stages)


def _is_expected_failure(metadata: dict[str, Any] | None, status: Any) -> bool:
    """A leaf graded PASS because it FAILED for its recorded `expect_fail` reason."""
    record = (metadata or {}).get("expected_fail")
    return isinstance(record, dict) and record.get("observed_status") == "FAIL" and status == "PASS"


def run_completion(
    leaves_run: int,
    planned_leaves: int | None,
    progress: dict[str, Any] | None,
) -> dict[str, Any]:
    """Whether every planned leaf executed.

    A checkpoint or an interrupted run carries `progress`, and its counts describe what
    had finished when the snapshot was taken, so it is never complete. Without a plan
    the executed leaves are the plan.
    """
    if progress is not None:
        planned = int(progress.get("expected_count") or planned_leaves or leaves_run)
    else:
        planned = leaves_run if planned_leaves is None else int(planned_leaves)
    return {
        "completed": progress is None and leaves_run >= planned,
        "leaves_planned": planned,
        "leaves_run": leaves_run,
    }


def executed_leaf_count(stages: list[StageResult]) -> int:
    """Leaves that ran: a leaf skipped after `--max-failures` never started."""
    return sum(1 for stage in stages if stage.stage in ITEM_STAGES and stage.status != "SKIP")


def run_is_complete(payload: dict[str, Any]) -> bool:
    """Read a recorded run-level result: did every planned leaf finish?"""
    if payload.get("interruption"):
        return False
    progress = payload.get("progress")
    if isinstance(progress, dict) and progress.get("state") in {"running", "interrupted"}:
        return False
    tests = payload.get("tests")
    return not (isinstance(tests, dict) and tests.get("completed") is False)


def incomplete_run_note(tests: Any) -> str | None:
    """One line for the console and error messages when a recorded run did not finish."""
    if not isinstance(tests, dict) or tests.get("completed") is not False:
        return None
    return (
        f"incomplete run: {tests.get('leaves_run', 0)} of {tests.get('leaves_planned', 0)} "
        "planned leaves ran, no pass rate"
    )


def _pass_rate(passing: int, total: int, completion: dict[str, Any] | None) -> float | None:
    # A truncated run has no denominator: the leaves that never ran are not failures,
    # and a rate over the executed subset reads as a grade the run did not earn.
    if completion is not None and not completion["completed"]:
        return None
    return round(passing / total, 4) if total else None


def _tests_summary(
    stages: list[StageResult], completion: dict[str, Any] | None = None
) -> dict[str, Any]:
    runs = [stage for stage in stages if stage.stage in ITEM_STAGES]
    total = len(runs)
    passing = sum(1 for stage in runs if stage.status == "PASS")
    failing = sum(1 for stage in runs if stage.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"})
    skipped = sum(1 for stage in runs if stage.status == "SKIP")
    expected_failing = sum(
        1 for stage in runs if _is_expected_failure(stage.metadata, stage.status)
    )
    summary = {
        "total": total,
        "passing": passing,
        "failing": failing,
        "skipped": skipped,
        "expected_failing": expected_failing,
        "pass_rate": _pass_rate(passing, total, completion),
    }
    if completion is not None:
        summary.update(completion)
    return summary


def coverage_summary(
    stages: list[StageResult], run_dir: Path, root: Path, coverage_requested: bool = False
) -> dict[str, Any]:
    cov_stages = [stage for stage in stages if stage.stage in {"cov_merge", "cov_report"}]
    if not cov_stages:
        return {
            "enabled": coverage_requested,
            "status": "SKIP",
            "total_percent": None,
            "metrics": {},
            "report": None,
            "summary": None,
            "threshold": None,
            "threshold_met": None,
            "merged": None,
            "manifest": None,
            "backend": None,
            "parser": None,
            "coverage_tool_version": None,
            "supported_metrics": [],
            "target": None,
            "build_fingerprint": None,
            "inputs": [],
            "details_available": None,
            "coverage_details": None,
            "coverage_details_raw": None,
            "policy_application": None,
            "comparison_key": None,
            "scope_fingerprint": None,
            "policy_fingerprint": None,
            "holes_summary": {"details_available": False},
            "policy_thresholds": [],
            "raw_metrics": {},
            "effective_metrics": {},
        }
    summary_path = run_dir / "cov" / "report" / "summary.json"
    manifest_path = run_dir / "cov" / "coverage.json"
    details_path = run_dir / "cov" / "report" / "coverage-details.json"
    raw_details_path = run_dir / "cov" / "report" / "coverage-details.raw.json"
    application_path = run_dir / "cov" / "report" / "policy-application.json"
    total_percent = None
    metrics: dict[str, Any] = {}
    threshold = None
    threshold_met = None
    summary_data: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            summary_data = data if isinstance(data, dict) else {}
            total_percent = summary_data.get("overall_percent")
            metrics = (
                summary_data.get("metrics", {})
                if isinstance(summary_data.get("metrics", {}), dict)
                else {}
            )
            threshold = summary_data.get("threshold")
            threshold_met = summary_data.get(
                "threshold_met",
                summary_data.get("status") == "PASS" if threshold is not None else None,
            )
        except (OSError, json.JSONDecodeError):
            pass
    manifest_data: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_data = data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
    manifest_artifacts = (
        manifest_data.get("artifacts") if isinstance(manifest_data.get("artifacts"), dict) else {}
    )
    details_data: dict[str, Any] = {}
    if details_path.is_file():
        try:
            data = json.loads(details_path.read_text(encoding="utf-8"))
            details_data = data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
    raw_metrics = {
        str(metric.get("metric_family")): metric.get("raw_percent")
        for metric in details_data.get("metrics", [])
        if isinstance(metric, dict) and metric.get("metric_family")
    }
    effective_metrics = {
        str(metric.get("metric_family")): metric.get("effective_percent")
        for metric in details_data.get("metrics", [])
        if isinstance(metric, dict) and metric.get("metric_family")
    }
    return {
        "enabled": True,
        "status": aggregate_status(cov_stages),
        "total_percent": total_percent,
        "metrics": metrics,
        "report": repo_rel(root, run_dir / "cov" / "report"),
        "summary": repo_rel(root, summary_path) if summary_path.is_file() else None,
        "threshold": threshold,
        "threshold_met": threshold_met,
        "merged": manifest_artifacts.get("merged"),
        "manifest": repo_rel(root, manifest_path) if manifest_path.is_file() else None,
        "backend": summary_data.get("backend") or manifest_data.get("backend"),
        "parser": manifest_data.get("parser"),
        "coverage_tool_version": manifest_data.get("tool_version"),
        "supported_metrics": manifest_data.get("supported_metrics", []),
        "target": manifest_data.get("target"),
        "build_fingerprint": manifest_data.get("build_fingerprint"),
        "inputs": manifest_data.get("inputs", []),
        "details_available": summary_data.get(
            "details_available", details_data.get("details_available")
        ),
        "coverage_details": (repo_rel(root, details_path) if details_path.is_file() else None),
        "coverage_details_raw": (
            repo_rel(root, raw_details_path) if raw_details_path.is_file() else None
        ),
        "policy_application": (
            repo_rel(root, application_path) if application_path.is_file() else None
        ),
        "comparison_key": summary_data.get("comparison_key"),
        "scope_fingerprint": summary_data.get("scope_fingerprint"),
        "policy_fingerprint": summary_data.get("policy_fingerprint"),
        "holes_summary": summary_data.get("holes_summary", {"details_available": False}),
        "policy_thresholds": summary_data.get("policy_thresholds", []),
        "raw_metrics": raw_metrics,
        "effective_metrics": effective_metrics,
    }


def _targets_summary(stages: list[StageResult]) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for stage in stages:
        metadata = stage.metadata or {}
        target_build = metadata.get("target_build")
        if not isinstance(target_build, dict):
            continue
        target = target_build.get("target") or stage.target
        if not isinstance(target, str) or not target:
            continue
        entry = dict(target_build)
        entry.setdefault("stages", [])
        if stage.stage not in entry["stages"]:
            entry["stages"].append(stage.stage)
        if target in targets:
            existing = targets[target]
            existing_stages = existing.setdefault("stages", [])
            for stage_name in entry["stages"]:
                if stage_name not in existing_stages:
                    existing_stages.append(stage_name)
            # Prefer explicit build-stage status over sim leaf synthesized metadata.
            if stage.stage in {"hdl_compile", "elaborate"}:
                targets[target] = {**existing, **entry, "stages": existing_stages}
        else:
            targets[target] = entry
    return targets


def _append_repeat_option(command: list[str], flag: str, values: list[str] | None) -> None:
    for value in values or []:
        command.extend([flag, str(value)])


def _rerun_command(flow: Flow, tool: str, job: dict[str, Any], args: Any | None) -> str:
    """Return a repo-root command that reruns one regression leaf."""
    stage = str(job.get("stage") or "sim")
    if stage == "regress":
        stage = "sim"

    command = ["python3", "tools/dv/run_dv.py", "--dut", flow.name]
    mode = str(getattr(args, "mode", "sim")) if args is not None else "sim"
    if mode != "sim":
        command.extend(["--mode", mode])
    command.extend(["--items", str(job.get("item", "")), "--stage", stage, "--tool", tool])
    seed = job.get("seed")
    if seed is not None and mode == "sim":
        command.extend(["--seed", str(seed)])

    if args is not None:
        if getattr(args, "run_mode", None):
            command.extend(["--run-mode", str(args.run_mode)])
        if getattr(args, "target", None):
            command.extend(["--target", str(args.target)])
        if getattr(args, "waves", None):
            command.extend(["--waves", str(args.waves)])
        if getattr(args, "waves_on_fail", None):
            command.extend(["--waves-on-fail", str(args.waves_on_fail)])
        for attr, flag in (
            ("wave_start", "--wave-start"),
            ("wave_end", "--wave-end"),
            ("wave_window", "--wave-window"),
            ("wave_margin", "--wave-margin"),
            ("wave_retention", "--wave-retention"),
        ):
            value = getattr(args, attr, None)
            if value:
                command.extend([flag, str(value)])
        if getattr(args, "cov", False):
            command.append("--cov")
        if getattr(args, "timeout", None) is not None:
            command.extend(["--timeout", str(args.timeout)])
        if getattr(args, "rebuild", False):
            command.append("--rebuild")
        _append_repeat_option(command, "--define", getattr(args, "define", None))
        _append_repeat_option(command, "--comp-arg", getattr(args, "comp_arg", None))
        _append_repeat_option(command, "--c-arg", getattr(args, "c_arg", None))
        _append_repeat_option(command, "--sim-arg", getattr(args, "sim_arg", None))
        _append_repeat_option(command, "--plusarg", getattr(args, "plusarg", None))

    return " ".join(shlex.quote(part) for part in command)


def _job_key(job: dict[str, Any]) -> tuple[str, Any, Any]:
    return (str(job.get("item", "")), job.get("seed"), job.get("target"))


def _attempt_summary(job: dict[str, Any]) -> dict[str, Any]:
    out = {
        "attempt": int(job.get("attempt", 0)),
        "status": job.get("status"),
        "reason": job.get("reason"),
        "return_code": job.get("return_code"),
        "duration_sec": job.get("duration_sec"),
        "log": job.get("log"),
        "artifacts": job.get("artifacts") or {},
        "failure_buckets": job.get("failure_buckets") or [],
        "parser": job.get("parser"),
        "result_json": job.get("result_json"),
        "metadata": job.get("metadata") or {},
    }
    if job.get("wave_debug"):
        out["wave_debug"] = job["wave_debug"]
    return {key: value for key, value in out.items() if value is not None}


def _leaf_attempts(jobs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    grouped: dict[tuple[str, Any, Any], list[dict[str, Any]]] = {}
    order: list[tuple[str, Any, Any]] = []
    for job in jobs:
        key = _job_key(job)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(job)

    leaves: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for key in order:
        attempts = sorted(grouped[key], key=lambda item: int(item.get("attempt", 0)))
        leaves.append((attempts[-1], attempts))
    return leaves


def _buckets_for_failed_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = [dict(bucket) for bucket in job.get("failure_buckets") or []]
    if buckets:
        return buckets
    return [
        {
            "kind": "unknown",
            "signature": str(job.get("reason") or "unclassified failure")[:120],
            "count": 1,
            "examples": [job["log"]] if job.get("log") else [],
        }
    ]


def _wave_replay_command(
    flow: Flow, tool: str, job: dict[str, Any], args: Any | None
) -> str | None:
    seed = job.get("seed")
    item = job.get("item")
    if args is None or seed is None or not item:
        return None
    wave_meta = (job.get("metadata") or {}).get("waves", {})
    wave_format = ""
    if isinstance(wave_meta, dict):
        wave_format = str(wave_meta.get("format") or "")
    if not wave_format:
        requested = getattr(args, "waves", None) or getattr(args, "waves_on_fail", None)
        wave_format = str(requested or WAVE_DEFAULT)
    return same_seed_replay_command(
        flow_name=flow.name,
        item=str(item),
        seed=int(seed),
        tool=tool,
        wave_format=wave_format,
        args=args,
    )


def _failed_test_record(
    final: dict[str, Any],
    attempts: list[dict[str, Any]],
    flow: Flow,
    tool: str,
    args: Any | None,
) -> dict[str, Any]:
    record = {
        "item": final.get("item"),
        "target": final.get("target"),
        "seed": final.get("seed"),
        "status": final.get("status"),
        "reason": final.get("reason"),
        "duration_sec": final.get("duration_sec"),
        "attempt_count": len(attempts),
        "attempts": [_attempt_summary(job) for job in attempts],
        "log": final.get("log"),
        "artifacts": final.get("artifacts") or {},
        "failure_buckets": _buckets_for_failed_job(final),
        "parser": final.get("parser"),
        "result_json": final.get("result_json"),
        "expected_fail": (final.get("metadata") or {}).get("expected_fail"),
        "rerun": _rerun_command(flow, tool, final, args),
    }
    wave_debug = final.get("wave_debug")
    if isinstance(wave_debug, dict):
        wave_debug_record = dict(wave_debug)
        wave_meta = (wave_debug_record.get("metadata") or {}).get("waves", {})
        if isinstance(wave_meta, dict):
            if wave_meta.get("viewer_commands"):
                wave_debug_record["viewer_commands"] = wave_meta["viewer_commands"]
            if wave_meta.get("same_seed_replay"):
                wave_debug_record["same_seed_replay"] = wave_meta["same_seed_replay"]
        record["wave_debug"] = wave_debug_record
    else:
        wave_replay = _wave_replay_command(flow, tool, final, args)
        if wave_replay:
            record["wave_replay"] = wave_replay
    return {key: value for key, value in record.items() if value is not None}


def _flaky_test_record(
    final: dict[str, Any],
    attempts: list[dict[str, Any]],
    flow: Flow,
    tool: str,
    args: Any | None,
) -> dict[str, Any]:
    failing_attempts = [job for job in attempts[:-1] if job.get("status") in NON_PASS_STATUSES]
    first_failure = failing_attempts[0]
    return {
        "item": final.get("item"),
        "target": final.get("target"),
        "seed": final.get("seed"),
        "final_status": final.get("status"),
        "flaky": True,
        "flaky_reason": "passed_after_retry",
        "attempt_count": len(attempts),
        "failing_attempts": len(failing_attempts),
        "first_fail_attempt": first_failure.get("attempt"),
        "first_failure_reason": first_failure.get("reason"),
        "passed_on_attempt": final.get("attempt"),
        "attempts": [_attempt_summary(job) for job in attempts],
        "log": final.get("log"),
        "result_json": final.get("result_json"),
        "rerun": _rerun_command(flow, tool, final, args),
    }


def _aggregate_failure_buckets(failed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for job in failed:
        for bucket in _buckets_for_failed_job(job):
            kind = str(bucket.get("kind", "unknown"))
            signature = str(bucket.get("signature", job.get("reason") or "unclassified failure"))
            key = (kind, signature)
            entry = grouped.setdefault(
                key,
                {
                    "kind": kind,
                    "signature": signature,
                    "count": 0,
                    "affected": [],
                    "examples": [],
                    "reason": job.get("reason"),
                },
            )
            entry["count"] += 1
            affected = {
                "item": job.get("item"),
                "target": job.get("target"),
                "seed": job.get("seed"),
                "status": job.get("status"),
            }
            entry["affected"].append({k: v for k, v in affected.items() if v is not None})
            examples = entry["examples"]
            for example in [*(bucket.get("examples") or []), job.get("log")]:
                if example and example not in examples and len(examples) < 5:
                    examples.append(example)
    return sorted(
        grouped.values(), key=lambda item: (-int(item["count"]), item["kind"], item["signature"])
    )


def _tests_summary_from_jobs(
    leaves: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    completion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_jobs = [final for final, _ in leaves]
    total = len([job for job in final_jobs if job.get("status") != "SKIP"])
    passing = sum(1 for job in final_jobs if job.get("status") == "PASS")
    failing = sum(1 for job in final_jobs if job.get("status") in NON_PASS_STATUSES)
    skipped = sum(1 for job in final_jobs if job.get("status") == "SKIP")
    flaky = sum(
        1
        for final, attempts in leaves
        if final.get("status") == "PASS"
        and any(job.get("status") in NON_PASS_STATUSES for job in attempts[:-1])
    )
    expected_failing = sum(
        1 for job in final_jobs if _is_expected_failure(job.get("metadata"), job.get("status"))
    )
    summary = {
        "total": total,
        "passing": passing,
        "failing": failing,
        "skipped": skipped,
        "flaky": flaky,
        "expected_failing": expected_failing,
        "pass_rate": _pass_rate(passing, total, completion),
    }
    if completion is not None:
        summary.update(completion)
    return summary


def _coverage_provenance(
    stages: list[StageResult],
    run_dir: Path,
    root: Path,
    tool: str,
    coverage_requested: bool,
) -> dict[str, Any]:
    payload = coverage_summary(stages, run_dir, root, coverage_requested)
    backend = payload.get("backend") or COVERAGE_BACKEND_BY_TOOL.get(tool, tool)
    has_valid_report = bool(
        payload.get("status") == "PASS"
        and payload.get("summary")
        and payload.get("total_percent") is not None
    )
    payload.update(
        {
            "requested": coverage_requested,
            "simulator": tool,
            "coverage_backend": backend,
            "coverage_class": "commercial_regression"
            if tool in SIGNOFF_COVERAGE_TOOLS
            else "contributor_baseline",
            "signoff_quality": bool(has_valid_report and tool in SIGNOFF_COVERAGE_TOOLS),
            "overall_percent": payload.get("total_percent"),
            "report_dir": payload.get("report"),
            "summary_json": payload.get("summary"),
        }
    )
    return payload


def _selection_payload(args: Any | None, items: list[str] | None) -> dict[str, Any]:
    if args is None:
        return {"expanded_items": items or [], "expanded_count": len(items or [])}
    return {
        "requested_items": list(getattr(args, "items", None) or []),
        "tags": list(getattr(args, "tag", None) or []),
        "expanded_items": items or [],
        "expanded_count": len(items or []),
        "run_mode": getattr(args, "run_mode", None),
        "reseed": getattr(args, "reseed", None),
        "retry": getattr(args, "retry", 0) or 0,
        "max_failures": getattr(args, "max_failures", None),
        "allow_duplicates": bool(getattr(args, "allow_duplicates", False)),
        "stages": list(getattr(args, "stage", None) or []),
    }


def regression_payload(
    *,
    flow: Flow,
    root: Path,
    tool: str,
    run_dir: Path,
    jobs: list[dict[str, Any]],
    stages: list[StageResult],
    args: Any | None = None,
    items: list[str] | None = None,
    elapsed_sec: float | None = None,
    status_override: str | None = None,
    progress: dict[str, Any] | None = None,
    interruption: dict[str, Any] | None = None,
    versions: dict[str, str] | None = None,
    git_metadata: dict[str, str] | None = None,
    planned_leaves: int | None = None,
) -> dict[str, Any]:
    """Aggregate regression leaf attempts into the durable scheduler summary."""
    versions = versions if versions is not None else tool_versions(root)
    leaves = _leaf_attempts(jobs)
    final_jobs = [final for final, _ in leaves]
    executed = sum(1 for job in final_jobs if job.get("status") != "SKIP")
    completion = run_completion(executed, planned_leaves, progress)
    failed_jobs = [job for job in final_jobs if job.get("status") in NON_PASS_STATUSES]
    flaky_leaves = [
        (final, attempts)
        for final, attempts in leaves
        if final.get("status") == "PASS"
        and any(job.get("status") in NON_PASS_STATUSES for job in attempts[:-1])
    ]
    failed_tests = [
        _failed_test_record(final, attempts, flow, tool, args)
        for final, attempts in leaves
        if final.get("status") in NON_PASS_STATUSES
    ]
    flaky_tests = [
        _flaky_test_record(final, attempts, flow, tool, args) for final, attempts in flaky_leaves
    ]
    status = status_override or (
        aggregate_status(stages)
        if stages
        else aggregate_status(
            [
                StageResult(
                    stage=str(job.get("stage", "sim")),
                    item=str(job.get("item", "")),
                    status=str(job.get("status", "UNKNOWN")),
                    return_code=int(job.get("return_code") or 0),
                    duration_sec=float(job.get("duration_sec") or 0.0),
                    started_at=str(job.get("started_at", "")),
                    ended_at=str(job.get("ended_at", "")),
                )
                for job in final_jobs
            ]
        )
    )

    coverage = _coverage_provenance(
        stages,
        run_dir,
        root,
        tool,
        bool(getattr(args, "cov", False)),
    )
    artifacts = {
        "result_json": repo_rel(root, run_dir / "result.json"),
        "regression_json": repo_rel(root, run_dir / "stages" / "regress" / "regression.json"),
    }
    for key in (
        "merged",
        "manifest",
        "report",
        "summary",
        "coverage_details",
        "coverage_details_raw",
        "policy_application",
    ):
        if coverage.get(key):
            artifacts[f"coverage_{key}"] = coverage[key]
    failure_buckets = _aggregate_failure_buckets(failed_jobs)
    if interruption:
        failure_buckets.append(
            {
                "kind": "interruption",
                "signature": str(interruption.get("reason") or "run interrupted")[:120],
                "count": 1,
                "affected": list((progress or {}).get("interrupted") or []),
                "examples": [],
            }
        )
    payload = {
        "schema_version": 1,
        "producer": "run_dv.py",
        "generated_at": datetime.now(UTC).isoformat(),
        "flow": flow.name,
        "kind": flow.kind,
        "framework": flow.framework,
        "visibility": flow.visibility,
        "runnability": flow.runnability,
        "license": flow.license,
        "tool": tool,
        "tool_version": primary_tool_version(tool, versions),
        "executor": getattr(args, "executor", None) or "local",
        "status": status,
        "exit_code": exit_code_for_status(status),
        "duration_sec": round(elapsed_sec, 3) if elapsed_sec is not None else None,
        "run_dir": repo_rel(root, run_dir),
        "artifact_root": repo_rel(root, run_dir),
        "artifacts": artifacts,
        "git": git_metadata if git_metadata is not None else git_info(root),
        "tool_versions": versions,
        "overrides": {"cli": cli_overrides(args)},
        "selection": _selection_payload(args, items),
        "tests": _tests_summary_from_jobs(leaves, completion),
        "coverage": coverage,
        "failure_buckets": failure_buckets,
        "failed_tests": failed_tests,
        "flaky_tests": flaky_tests,
        "rerun_commands": [
            record["rerun"] for record in [*failed_tests, *flaky_tests] if record.get("rerun")
        ],
        "jobs": jobs,
    }
    if _has_formal(flow, stages):
        payload["formal"] = formal_summary(stages)
    overlay = flow.raw.get("adopter_overlay")
    if overlay:
        payload["overlay"] = overlay
    overlay_env = flow.raw.get("adopter_overlay_env")
    if overlay_env:
        payload["overlay_env"] = dict(overlay_env)
    site = _site_layer_label(args)
    if site:
        payload["site"] = site
    if progress is not None:
        payload["progress"] = progress
    if interruption is not None:
        payload["interruption"] = interruption
    return payload


def result_payload(
    *,
    flow: Flow,
    root: Path,
    tool: str,
    run_dir: Path,
    stages: list[StageResult],
    dry_run: bool,
    items: list[str] | None = None,
    label: str = "",
    args: Any | None = None,
    executor: str = "local",
    status_override: str | None = None,
    progress: dict[str, Any] | None = None,
    interruption: dict[str, Any] | None = None,
    versions: dict[str, str] | None = None,
    git_metadata: dict[str, str] | None = None,
    planned_leaves: int | None = None,
) -> dict[str, Any]:
    status = status_override or aggregate_status(stages)
    versions = versions if versions is not None else tool_versions(root)
    completion = run_completion(executed_leaf_count(stages), planned_leaves, progress)
    payload = {
        "schema_version": 1,
        "flow": flow.name,
        "kind": flow.kind,
        "description": flow.description,
        "framework": flow.framework,
        "visibility": flow.visibility,
        "runnability": flow.runnability,
        "license": flow.license,
        "tool": tool,
        "tool_version": primary_tool_version(tool, versions),
        "executor": executor,
        "label": label,
        "status": status,
        "exit_code": exit_code_for_status(status),
        "dry_run": dry_run,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_dir": repo_rel(root, run_dir),
        "items": items or [],
        "overrides": {"cli": cli_overrides(args)},
        "tests": _tests_summary(stages, completion),
        "coverage": coverage_summary(stages, run_dir, root, bool(getattr(args, "cov", False))),
        "git": git_metadata if git_metadata is not None else git_info(root),
        "tool_versions": versions,
        "stages": [_stage_dict(stage) for stage in stages],
    }
    targets = _targets_summary(stages)
    if targets:
        payload["targets"] = targets
    if _has_formal(flow, stages):
        payload["formal"] = formal_summary(stages)
    overlay = flow.raw.get("adopter_overlay")
    if overlay:
        # The adopter overlay applied to this run (--overlay / OCAH_DV_OVERLAY), so the
        # result records the exact config layers that produced it.
        payload["overlay"] = overlay
    overlay_env = flow.raw.get("adopter_overlay_env")
    if overlay_env:
        payload["overlay_env"] = dict(overlay_env)
    site = _site_layer_label(args)
    if site:
        payload["site"] = site
    selection = {
        key: list(getattr(args, f"_{key}", []) or []) if args is not None else []
        for key in ("skipped_unimplemented", "skipped_excluded")
    }
    if any(selection.values()):
        payload["selection"] = selection
    if progress is not None:
        payload["progress"] = progress
    if interruption is not None:
        payload["interruption"] = interruption
    return payload


def fragment_payload(
    *,
    flow: Flow,
    root: Path,
    tool: str,
    run_dir: Path,
    item: str,
    seed: int,
    result: StageResult,
) -> dict[str, Any]:
    """Leaf result for one (test, seed, attempt) run."""
    payload = {
        "schema_version": 1,
        "flow": flow.name,
        "kind": flow.kind,
        "framework": flow.framework,
        "tool": tool,
        "item": item,
        "seed": seed,
        "status": result.status,
        "exit_code": exit_code_for_status(result.status),
        "return_code": result.return_code,
        "reason": result.reason,
        "run_dir": repo_rel(root, run_dir),
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "duration_sec": round(result.duration_sec, 3),
        "log": result.log,
        "artifacts": result.artifacts or {},
        "failure_buckets": result.failure_buckets or [],
        "parser": result.parser,
    }
    if result.metadata:
        payload["metadata"] = result.metadata
        if result.metadata.get("attempt") is not None:
            payload["attempt"] = result.metadata["attempt"]
    if result.target:
        payload["target"] = result.target
    if result.formal is not None:
        payload["formal"] = result.formal
    target_build = (result.metadata or {}).get("target_build")
    if isinstance(target_build, dict):
        payload["target_build"] = target_build
    return payload


def rollup_payload(
    *,
    flow: Flow,
    root: Path,
    tool: str,
    run_dir: Path,
    item: str,
    runs: list[tuple[int, StageResult]],
) -> dict[str, Any]:
    """Per-test rollup across that test's seeds/attempts."""
    leaves = [result for _, result in runs]
    status = aggregate_status(leaves)
    payload = {
        "schema_version": 1,
        "flow": flow.name,
        "tool": tool,
        "item": item,
        "status": status,
        "exit_code": exit_code_for_status(status),
        "run_dir": repo_rel(root, run_dir),
        "tests": _tests_summary(leaves),
        "runs": [
            {
                "seed": seed,
                "status": result.status,
                "reason": result.reason,
                "log": result.log,
                "artifacts": result.artifacts or {},
            }
            for seed, result in runs
        ],
    }
    target = next((result.target for _, result in runs if result.target), None)
    if target:
        payload["target"] = target
    if any(result.formal is not None for result in leaves):
        payload["formal"] = formal_summary(leaves)
    return payload


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
