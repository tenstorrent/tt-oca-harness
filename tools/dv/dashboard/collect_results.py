# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Collect a DUT's native `run_dv.py` result.json into normalized dashboard result JSON.

Dashboard collection consumes only the normalized `result.json` that `run_dv.py` emits for every
DUT.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from runlib.config import load_test_catalog
from runlib.duts import resolve_dut
from runlib.models import ConfigError, Flow, TestCatalog, TestEntry
from runlib.paths import dut_runs_root, dv_root, repo_path, repo_root

from dashboard.schema import STATUS_FAIL, STATUS_PASS, STATUS_UNKNOWN, make_result, write_json


def _repo_rel(repo_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path.resolve())


def _repo_rel_text(repo_root: Path, path: Path | str | None) -> str:
    if path in (None, ""):
        return ""
    return _repo_rel(repo_root, Path(str(path)))


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _recorded_run_root(
    result: dict[str, Any],
    regression: dict[str, Any] | None,
) -> Path | None:
    value = result.get("run_dir")
    if not value and regression:
        value = regression.get("run_dir") or regression.get("artifact_root")
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _relative_to_recorded_root(
    repo_root: Path,
    path: Path,
    recorded_run_root: Path | None,
) -> Path | None:
    if recorded_run_root is None:
        return None
    absolute = path if path.is_absolute() else repo_root / path
    recorded_absolute = (
        recorded_run_root if recorded_run_root.is_absolute() else repo_root / recorded_run_root
    )
    try:
        return absolute.relative_to(recorded_absolute)
    except ValueError:
        pass

    path_parts = path.parts
    recorded_parts = recorded_run_root.parts
    if recorded_run_root.is_absolute() and not path.is_absolute():
        # A repo-relative artifact can be paired with an absolute recorded run
        # root. Match the longest recorded-root suffix at the path's start.
        for index in range(len(recorded_parts)):
            suffix = recorded_parts[index:]
            if path_parts[: len(suffix)] == suffix:
                return Path(*path_parts[len(suffix) :])
        return None
    if recorded_run_root.is_absolute():
        return None

    # Absolute paths recorded on another worker still contain the repo-relative
    # run root. Recover the suffix without depending on that worker's checkout.
    width = len(recorded_parts)
    for index in range(len(path_parts) - width, -1, -1):
        if path_parts[index : index + width] == recorded_parts:
            return Path(*path_parts[index + width :])
    return None


def _artifact_path(
    repo_root: Path,
    run_root: Path,
    value: Any,
    recorded_run_root: Path | None = None,
) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    relative = _relative_to_recorded_root(repo_root, path, recorded_run_root)
    if relative is not None:
        return run_root / relative
    if path.is_absolute():
        return path
    repo_candidate = repo_root / path
    if repo_candidate.exists():
        return repo_candidate
    return run_root / path


def _artifact_text(
    repo_root: Path,
    run_root: Path,
    value: Any,
    recorded_run_root: Path | None,
) -> str:
    path = _artifact_path(repo_root, run_root, value, recorded_run_root)
    return _repo_rel(repo_root, path) if path is not None else ""


def _path_values(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, str) and entry]
    return []


def _rebase_artifacts(
    repo_root: Path,
    run_root: Path,
    artifacts: dict[str, Any],
    recorded_run_root: Path | None,
) -> dict[str, Any]:
    rebased: dict[str, Any] = {}
    for key, value in artifacts.items():
        path_key = key in _PATH_ARTIFACT_KEYS or key.startswith("debug_")
        if not path_key:
            rebased[key] = value
            continue
        if isinstance(value, str):
            rebased[key] = _artifact_text(
                repo_root,
                run_root,
                value,
                recorded_run_root,
            )
        elif isinstance(value, list):
            rebased[key] = [
                _artifact_text(
                    repo_root,
                    run_root,
                    entry,
                    recorded_run_root,
                )
                if isinstance(entry, str)
                else entry
                for entry in value
            ]
        else:
            rebased[key] = value
    return rebased


def _rebase_parser(
    repo_root: Path,
    run_root: Path,
    parser: Any,
    recorded_run_root: Path | None,
) -> Any:
    if not isinstance(parser, dict):
        return parser
    rebased = dict(parser)
    evidence_out = []
    for evidence in parser.get("evidence") or []:
        if not isinstance(evidence, dict):
            evidence_out.append(evidence)
            continue
        entry = dict(evidence)
        if entry.get("path"):
            entry["path"] = _artifact_text(
                repo_root,
                run_root,
                entry["path"],
                recorded_run_root,
            )
        evidence_out.append(entry)
    if "evidence" in parser:
        rebased["evidence"] = evidence_out
    return rebased


def _rebase_failure_buckets(
    repo_root: Path,
    run_root: Path,
    buckets: Any,
    recorded_run_root: Path | None,
) -> Any:
    if not isinstance(buckets, list):
        return buckets
    rebased = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            rebased.append(bucket)
            continue
        entry = dict(bucket)
        if isinstance(entry.get("examples"), list):
            entry["examples"] = _rebase_artifacts(
                repo_root,
                run_root,
                {"examples": entry["examples"]},
                recorded_run_root,
            )["examples"]
        rebased.append(entry)
    return rebased


def _rebase_result_record(
    repo_root: Path,
    run_root: Path,
    record: dict[str, Any],
    recorded_run_root: Path | None,
) -> dict[str, Any]:
    rebased = dict(record)
    for key in ("log", "result_json"):
        if rebased.get(key):
            rebased[key] = _artifact_text(
                repo_root,
                run_root,
                rebased[key],
                recorded_run_root,
            )
    if isinstance(rebased.get("artifacts"), dict):
        rebased["artifacts"] = _rebase_artifacts(
            repo_root,
            run_root,
            rebased["artifacts"],
            recorded_run_root,
        )
    if "parser" in rebased:
        rebased["parser"] = _rebase_parser(
            repo_root,
            run_root,
            rebased["parser"],
            recorded_run_root,
        )
    if isinstance(rebased.get("failure_buckets"), list):
        rebased["failure_buckets"] = _rebase_failure_buckets(
            repo_root,
            run_root,
            rebased["failure_buckets"],
            recorded_run_root,
        )
    for key in ("attempts",):
        if isinstance(rebased.get(key), list):
            rebased[key] = [
                _rebase_result_record(
                    repo_root,
                    run_root,
                    entry,
                    recorded_run_root,
                )
                if isinstance(entry, dict)
                else entry
                for entry in rebased[key]
            ]
    if isinstance(rebased.get("wave_debug"), dict):
        rebased["wave_debug"] = _rebase_result_record(
            repo_root,
            run_root,
            rebased["wave_debug"],
            recorded_run_root,
        )
    return rebased


def _rebase_regression(
    repo_root: Path,
    run_root: Path,
    regression: dict[str, Any],
    recorded_run_root: Path | None,
) -> dict[str, Any]:
    rebased = dict(regression)
    if isinstance(rebased.get("artifacts"), dict):
        rebased["artifacts"] = _rebase_artifacts(
            repo_root,
            run_root,
            rebased["artifacts"],
            recorded_run_root,
        )
    if isinstance(rebased.get("coverage"), dict):
        rebased["coverage"] = _rebase_artifacts(
            repo_root,
            run_root,
            rebased["coverage"],
            recorded_run_root,
        )
    if isinstance(rebased.get("failure_buckets"), list):
        rebased["failure_buckets"] = _rebase_failure_buckets(
            repo_root,
            run_root,
            rebased["failure_buckets"],
            recorded_run_root,
        )
    for key in ("jobs", "failed_tests", "flaky_tests"):
        if isinstance(rebased.get(key), list):
            rebased[key] = [
                _rebase_result_record(
                    repo_root,
                    run_root,
                    entry,
                    recorded_run_root,
                )
                if isinstance(entry, dict)
                else entry
                for entry in rebased[key]
            ]
    return rebased


def _native_result_path(repo_root: Path, flow: Flow, run_dir: Path | None) -> Path | None:
    """Locate a `run_dv.py` result.json: an explicit run dir/file, else `build/runs/latest/`."""
    if run_dir is not None:
        if run_dir.is_file() and run_dir.name == "result.json":
            return run_dir
        candidate = run_dir / "result.json"
        return candidate if candidate.is_file() else None
    latest = dut_runs_root(repo_path(repo_root, flow.root)) / "latest" / "result.json"
    return latest if latest.is_file() else None


def _native_timing(stages: list[dict[str, Any]]) -> dict[str, Any]:
    starts = [stage.get("started_at") for stage in stages if stage.get("started_at")]
    ends = [stage.get("ended_at") for stage in stages if stage.get("ended_at")]
    duration = sum(float(stage.get("duration_sec") or 0.0) for stage in stages)
    return {
        "start_time": min(starts) if starts else "",
        "end_time": max(ends) if ends else "",
        "duration_sec": round(duration, 3) if stages else None,
    }


def _native_failure_buckets(
    result: dict[str, Any], regression: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for stage in result.get("stages", []):
        for bucket in stage.get("failure_buckets") or []:
            key = (bucket.get("kind", ""), bucket.get("signature", ""))
            existing = merged.get(key)
            if existing:
                existing["count"] = int(existing.get("count", 0)) + int(bucket.get("count", 1))
            else:
                merged[key] = dict(bucket)
    if regression:
        for bucket in regression.get("failure_buckets") or []:
            if not isinstance(bucket, dict):
                continue
            key = (bucket.get("kind", ""), bucket.get("signature", ""))
            existing = merged.get(key)
            if existing:
                existing["count"] = int(existing.get("count", 0)) + int(bucket.get("count", 1))
            else:
                merged[key] = dict(bucket)
    return list(merged.values())


def _groups_by_test(catalog: TestCatalog) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {name: [] for name in catalog.tests}
    for group, members in catalog.groups.items():
        for member in members:
            groups.setdefault(member, []).append(group)
    return groups


_CATEGORY_PRIORITY = (
    "smoke",
    "ci",
    "regression",
    "functional",
    "coverage",
    "firmware",
    "system",
    "subsystem",
)

_PATH_ARTIFACT_KEYS = {
    "coverage",
    "coverage_coverage_details",
    "coverage_coverage_details_raw",
    "coverage_design",
    "coverage_details",
    "coverage_details_raw",
    "coverage_inputs",
    "coverage_manifest",
    "coverage_merged",
    "coverage_policy_application",
    "coverage_report",
    "coverage_summary",
    "debug_result_json",
    "env",
    "examples",
    "inputs",
    "log",
    "manifest",
    "merged",
    "policy_application",
    "regression_json",
    "report",
    "report_dir",
    "result_json",
    "results_xml",
    "script",
    "summary",
    "summary_json",
    "wave_debug_context",
    "wave_dump_script",
    "wave_files",
    "wave_log",
    "waves",
}


def _test_metadata(
    flow: Flow, catalog: TestCatalog, groups_by_test: dict[str, list[str]], item: str | None
) -> dict[str, Any]:
    if not item:
        return {"name": "", "module": "", "tags": [], "groups": [], "category": flow.name}
    test: TestEntry | None = catalog.tests.get(item)
    tags = list(test.tags or []) if test else []
    groups = groups_by_test.get(item, [])
    category = next((tag for tag in _CATEGORY_PRIORITY if tag in tags), None)
    if category is None:
        category = groups[0] if groups else flow.name
    return {
        "name": item,
        "module": test.module if test else item,
        "tags": tags,
        "groups": groups,
        "category": category,
        "target": test.target if test else None,
    }


def _parser_junit_paths(parser: Any) -> list[str]:
    if not isinstance(parser, dict):
        return []
    paths: list[str] = []
    for evidence in parser.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        if evidence.get("kind") in {"results_xml", "junit_xml"} and evidence.get("path"):
            paths.append(str(evidence["path"]))
    return paths


def _guess_junit_from_log(
    repo_root: Path,
    run_root: Path,
    log: Any,
    recorded_run_root: Path | None,
) -> str:
    log_path = _artifact_path(repo_root, run_root, log, recorded_run_root)
    if log_path is None:
        return ""
    leaf_dir = log_path.parent.parent if log_path.parent.name == "logs" else log_path.parent
    return _repo_rel(repo_root, leaf_dir / "results" / "results.xml")


def _read_leaf_result(
    repo_root: Path,
    run_root: Path,
    result_json: Any,
    recorded_run_root: Path | None,
) -> dict[str, Any] | None:
    path = _artifact_path(repo_root, run_root, result_json, recorded_run_root)
    if path is None or not path.is_file():
        return None
    return _safe_load_json(path)


def _test_detail_from_record(
    *,
    repo_root: Path,
    run_root: Path,
    flow: Flow,
    catalog: TestCatalog,
    groups_by_test: dict[str, list[str]],
    record: dict[str, Any],
    recorded_run_root: Path | None,
    fallback_stage: str = "sim",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    item = record.get("item")
    if not isinstance(item, str) or not item:
        return None, [], []

    leaf = (
        _read_leaf_result(
            repo_root,
            run_root,
            record.get("result_json"),
            recorded_run_root,
        )
        or {}
    )
    merged = {**record, **{k: v for k, v in leaf.items() if v not in (None, "", [], {})}}
    meta = _test_metadata(flow, catalog, groups_by_test, item)
    recorded_artifacts = (
        merged.get("artifacts") if isinstance(merged.get("artifacts"), dict) else {}
    )
    artifacts = _rebase_artifacts(
        repo_root,
        run_root,
        recorded_artifacts,
        recorded_run_root,
    )
    parser = merged.get("parser")
    junit_values = _path_values(recorded_artifacts.get("results_xml"))
    if not junit_values:
        junit_values = _parser_junit_paths(parser)
    junit_paths = [
        _artifact_text(repo_root, run_root, value, recorded_run_root) for value in junit_values
    ]
    junit_paths = [path for path in junit_paths if path]
    if not junit_paths:
        guessed = _guess_junit_from_log(
            repo_root,
            run_root,
            merged.get("log"),
            recorded_run_root,
        )
        if guessed:
            junit_paths.append(guessed)

    result_json_path = _artifact_text(
        repo_root,
        run_root,
        record.get("result_json"),
        recorded_run_root,
    )
    if not result_json_path:
        flat = run_root / item / "result.json"
        if flat.is_file():
            result_json_path = _repo_rel(repo_root, flat)
    log_path = _artifact_text(
        repo_root,
        run_root,
        merged.get("log"),
        recorded_run_root,
    )
    parser_evidence = []
    if isinstance(parser, dict):
        for evidence in (parser.get("evidence") or [])[:5]:
            if not isinstance(evidence, dict):
                continue
            entry = dict(evidence)
            if entry.get("path"):
                entry["path"] = _artifact_text(
                    repo_root,
                    run_root,
                    entry["path"],
                    recorded_run_root,
                )
            parser_evidence.append(entry)

    detail = {
        "name": meta["name"],
        "module": meta["module"],
        "category": meta["category"],
        "tags": meta["tags"],
        "groups": meta["groups"],
        "target": merged.get("target") or meta.get("target"),
        "seed": merged.get("seed"),
        "attempt": merged.get("attempt"),
        "stage": merged.get("stage", fallback_stage),
        "status": merged.get("status", STATUS_UNKNOWN),
        "duration_sec": merged.get("duration_sec"),
        "reason": merged.get("reason", ""),
        "log": log_path,
        "result_json": result_json_path,
        "junit_xml": junit_paths[0] if junit_paths else "",
        "artifacts": artifacts,
        "failure_buckets": merged.get("failure_buckets") or [],
        "parser": {
            "policy": parser.get("policy") if isinstance(parser, dict) else None,
            "status_source": parser.get("status_source") if isinstance(parser, dict) else None,
            "evidence": parser_evidence,
        },
    }
    junit_entries = [
        {
            "item": item,
            "seed": detail.get("seed"),
            "attempt": detail.get("attempt"),
            "path": path,
            "exists": bool(
                (repo_root / path).is_file()
                if not Path(path).is_absolute()
                else Path(path).is_file()
            ),
        }
        for path in dict.fromkeys(junit_paths)
    ]
    warnings = [
        f"JUnit XML missing for {item}: {entry['path']}"
        for entry in junit_entries
        if not entry["exists"]
    ]
    if not junit_entries and detail["status"] not in {"SKIP"}:
        warnings.append(f"JUnit XML not recorded for {item}")
    return detail, junit_entries, warnings


def _test_details_from_layout(
    repo_root: Path,
    run_root: Path,
    flow: Flow,
    catalog: TestCatalog,
    groups_by_test: dict[str, list[str]],
    recorded_run_root: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    details: list[dict[str, Any]] = []
    junit_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in sorted(run_root.glob("*/result.json")):
        if path.parent.name == "stages":
            continue
        data = _safe_load_json(path)
        if not data or not data.get("item"):
            continue
        record = dict(data)
        record.setdefault("result_json", _repo_rel(repo_root, path))
        detail, junit, warn = _test_detail_from_record(
            repo_root=repo_root,
            run_root=run_root,
            flow=flow,
            catalog=catalog,
            groups_by_test=groups_by_test,
            record=record,
            recorded_run_root=recorded_run_root,
        )
        if detail:
            details.append(detail)
            junit_entries.extend(junit)
            warnings.extend(warn)
    return details, junit_entries, warnings


def _collect_test_details(
    repo_root: Path,
    run_root: Path,
    flow: Flow,
    result: dict[str, Any],
    regression: dict[str, Any] | None,
    recorded_run_root: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    catalog = load_test_catalog(flow, repo_root)
    groups_by_test = _groups_by_test(catalog)
    details: list[dict[str, Any]] = []
    junit_entries: list[dict[str, Any]] = []
    warnings: list[str] = []

    records: list[dict[str, Any]] = []
    if regression:
        for job in regression.get("jobs") or []:
            if isinstance(job, dict) and not job.get("debug_only"):
                records.append(job)
    else:
        for stage in result.get("stages") or []:
            if (
                isinstance(stage, dict)
                and stage.get("name") in {"sim", "regress"}
                and stage.get("item")
            ):
                record = dict(stage)
                item = str(stage.get("item"))
                result_json = run_root / item / "result.json"
                if result_json.is_file():
                    record.setdefault("result_json", _repo_rel(repo_root, result_json))
                records.append(record)

    seen_keys: set[tuple[Any, Any, Any]] = set()
    for record in records:
        detail, junit, warn = _test_detail_from_record(
            repo_root=repo_root,
            run_root=run_root,
            flow=flow,
            catalog=catalog,
            groups_by_test=groups_by_test,
            record=record,
            recorded_run_root=recorded_run_root,
        )
        if detail is None:
            continue
        key = (detail.get("name"), detail.get("seed"), detail.get("attempt"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        details.append(detail)
        junit_entries.extend(junit)
        warnings.extend(warn)

    if not details:
        layout_details, layout_junit, layout_warnings = _test_details_from_layout(
            repo_root,
            run_root,
            flow,
            catalog,
            groups_by_test,
            recorded_run_root,
        )
        details.extend(layout_details)
        junit_entries.extend(layout_junit)
        warnings.extend(layout_warnings)

    dedup_junit = list(
        {
            (entry.get("item"), entry.get("seed"), entry.get("attempt"), entry.get("path")): entry
            for entry in junit_entries
        }.values()
    )
    return details, dedup_junit, warnings


def _load_regression(repo_root: Path, run_root: Path) -> dict[str, Any] | None:
    path = run_root / "stages" / "regress" / "regression.json"
    data = _safe_load_json(path)
    if data is None:
        return None
    data = dict(data)
    data.setdefault("artifacts", {})
    if isinstance(data["artifacts"], dict):
        data["artifacts"]["regression_json"] = _repo_rel(repo_root, path)
    return data


def _run_metadata(
    repo_root: Path,
    run_root: Path,
    result_path: Path,
    result: dict[str, Any],
    run_json: dict[str, Any] | None,
    regression: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "run_dir": result.get("run_dir", _repo_rel(repo_root, run_root)),
        "result_json": _repo_rel(repo_root, result_path),
        "run_json": _repo_rel(repo_root, run_root / "run.json")
        if (run_root / "run.json").is_file()
        else "",
        "label": result.get("label", ""),
        "items": result.get("items") or [],
        "stages": [
            stage.get("name") for stage in result.get("stages", []) if isinstance(stage, dict)
        ],
        "tool": result.get("tool", ""),
        "tool_version": result.get("tool_version", ""),
        "tool_versions": result.get("tool_versions", {}),
        "executor": result.get("executor", regression.get("executor", "") if regression else ""),
        "generated_at": result.get("generated_at", ""),
        "dry_run": result.get("dry_run", False),
        "overrides": result.get("overrides", {}),
        "git": result.get("git", {}),
        "selection": regression.get("selection", {}) if regression else {},
        "invocation": run_json or {},
        "progress": result.get(
            "progress",
            regression.get("progress", {}) if regression else {},
        ),
        "interruption": result.get(
            "interruption",
            regression.get("interruption", {}) if regression else {},
        ),
    }


def _collect_native_result(
    repo_root: Path, flow: Flow, run_dir: Path | None
) -> dict[str, Any] | None:
    """Consume a normalized `run_dv.py` result.json. Returns None if no native result exists."""
    path = _native_result_path(repo_root, flow, run_dir)
    if path is None:
        return None
    result = _safe_load_json(path)
    if result is None:
        return None
    if not isinstance(result, dict) or "status" not in result:
        return None

    run_root = path.parent
    run_json_path = run_root / "run.json"
    run_json = _safe_load_json(run_json_path) if run_json_path.is_file() else None
    regression = _load_regression(repo_root, run_root)
    recorded_run_root = _recorded_run_root(result, regression)
    if regression is not None:
        regression = _rebase_regression(
            repo_root,
            run_root,
            regression,
            recorded_run_root,
        )
    tests_detail, junit_xml, warnings = _collect_test_details(
        repo_root,
        run_root,
        flow,
        result,
        regression,
        recorded_run_root,
    )

    raw_status = str(result.get("status", STATUS_UNKNOWN))
    # Dashboard buckets are PASS / FAIL / UNKNOWN; ERROR and TIMEOUT are non-passing failures.
    status = raw_status if raw_status in {STATUS_PASS, STATUS_UNKNOWN} else STATUS_FAIL

    tests = result.get("tests") or {}
    coverage = _rebase_artifacts(
        repo_root,
        run_root,
        result.get("coverage") if isinstance(result.get("coverage"), dict) else {},
        recorded_run_root,
    )
    timing = _native_timing(result.get("stages", []))

    artifacts: dict[str, Any] = {"result_json": _repo_rel(repo_root, path)}
    if result.get("run_dir"):
        artifacts["run_dir"] = str(result["run_dir"])
    if run_json_path.is_file():
        artifacts["run_json"] = _repo_rel(repo_root, run_json_path)
    if regression:
        reg_artifacts = (
            regression.get("artifacts") if isinstance(regression.get("artifacts"), dict) else {}
        )
        if reg_artifacts.get("regression_json"):
            artifacts["regression_json"] = str(reg_artifacts["regression_json"])
    sim_stages = [
        s for s in result.get("stages", []) if s.get("name") in {"sim", "regress"} and s.get("log")
    ]
    # Prefer a failing test's log for triage, else the first run's log.
    sim_stage = next(
        (s for s in sim_stages if s.get("status") != STATUS_PASS),
        sim_stages[0] if sim_stages else None,
    )
    if sim_stage:
        artifacts["log"] = _artifact_text(
            repo_root,
            run_root,
            sim_stage["log"],
            recorded_run_root,
        )
    for key in (
        "report",
        "summary",
        "merged",
        "manifest",
        "coverage_details",
        "coverage_details_raw",
        "policy_application",
    ):
        value = coverage.get(key)
        if value:
            artifacts[f"coverage_{key}"] = value

    return make_result(
        repo_root=repo_root,
        flow=flow.name,
        kind=str(result.get("kind", flow.kind)),
        status=status,
        tool=str(result.get("tool", flow.default_tool)),
        framework=str(result.get("framework", flow.framework)),
        start_time=timing["start_time"],
        end_time=timing["end_time"],
        duration_sec=timing["duration_sec"],
        tests_total=int(tests.get("total") or 0),
        tests_passing=int(tests.get("passing") or 0),
        tests_completed=tests.get("completed")
        if isinstance(tests.get("completed"), bool)
        else None,
        coverage_percent=coverage.get("total_percent"),
        coverage_breakdown={
            k.removesuffix("_percent"): v for k, v in (coverage.get("metrics") or {}).items()
        },
        coverage_details=coverage,
        artifacts=artifacts,
        failure_buckets=_rebase_failure_buckets(
            repo_root,
            run_root,
            _native_failure_buckets(result, regression),
            recorded_run_root,
        ),
        source={
            "collector": "run_dv-result",
            "label": str(result.get("label", "")),
            "native_status": raw_status,
        },
        run_metadata=_run_metadata(repo_root, run_root, path, result, run_json, regression),
        tests_detail=tests_detail,
        junit_xml=junit_xml,
        regression=regression,
        warnings=warnings,
    )


def collect_flow_result(repo_root: Path, flow: Flow, run_dir: Path | None) -> dict[str, Any]:
    """Normalize one DUT's native result.json; UNKNOWN if the DUT has not produced one yet."""
    native = _collect_native_result(repo_root, flow, run_dir)
    if native is not None:
        return native

    return make_result(
        repo_root=repo_root,
        flow=flow.name,
        kind=flow.kind,
        status=STATUS_UNKNOWN,
        tool=flow.default_tool,
        framework=flow.framework,
        failure_buckets=[
            {
                "signature": f"no run_dv.py result.json found for DUT `{flow.name}` "
                "(run the DUT first, or pass --run-dir)",
                "count": 1,
            }
        ],
        source={"collector": "none"},
    )


# The files of a coverage report that are staged beside the normalized result;
# the details files, the annotated sources, and the merged database stay in the
# run tree.
_STAGED_REPORT_FILES = (
    ("summary", "summary.json"),
    ("policy_application", "policy-application.json"),
)


def stage_coverage_artifacts(
    repo_root_path: Path,
    result: dict[str, Any],
    output: Path,
) -> None:
    coverage = result.get("coverage")
    if not isinstance(coverage, dict):
        return
    flow = str(result.get("flow") or "unknown")
    destination = output.parent / "artifacts" / flow / "coverage"
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = result.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        result["artifacts"] = artifacts

    report_value = coverage.get("report")
    if isinstance(report_value, str) and report_value:
        source = repo_path(repo_root_path, report_value)
        if source.is_dir():
            report_destination = destination / "report"
            if report_destination.exists():
                shutil.rmtree(report_destination)
            report_destination.mkdir(parents=True)
            staged_report = str(report_destination.relative_to(output.parent))
            coverage["source_report"] = report_value
            coverage["report"] = staged_report
            artifacts["coverage_report"] = staged_report
            for key, filename in _STAGED_REPORT_FILES:
                staged_source = source / filename
                if not staged_source.is_file():
                    continue
                staged = report_destination / filename
                shutil.copy2(staged_source, staged)
                coverage[f"source_{key}"] = coverage.get(key)
                coverage[key] = str(staged.relative_to(output.parent))
                artifacts[f"coverage_{key}"] = coverage[key]

    manifest_value = coverage.get("manifest")
    if isinstance(manifest_value, str) and manifest_value:
        source = repo_path(repo_root_path, manifest_value)
        if source.is_file():
            staged = destination / "coverage.json"
            shutil.copy2(source, staged)
            coverage["source_manifest"] = manifest_value
            coverage["manifest"] = str(staged.relative_to(output.parent))
            artifacts["coverage_manifest"] = coverage["manifest"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dut", required=True, help="DUT name (duts.toml or hw/** convention)")
    parser.add_argument(
        "--framework",
        help="framework view to resolve (e.g. uvm); default: the DUT's default_framework",
    )
    parser.add_argument("--run-dir", help="run directory or result.json to parse")
    parser.add_argument("--output", help="output result.json path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root_path = repo_root(Path(__file__))
        flow = resolve_dut(repo_root_path, args.dut, framework=args.framework)
        run_dir = Path(args.run_dir).resolve() if args.run_dir else None
        result = collect_flow_result(repo_root_path, flow, run_dir)
        collected_framework = str(result.get("framework", ""))
        if (
            args.framework
            and (result.get("source") or {}).get("collector") == "run_dv-result"
            and collected_framework != args.framework
        ):
            # A result.json that records a different framework is a mispaired --run-dir.
            raise ConfigError(
                f"--framework {args.framework} was requested but the collected result.json "
                f"records framework `{collected_framework}` — wrong --run-dir pairing?"
            )
        output = (
            Path(args.output).resolve()
            if args.output
            else dv_root(repo_root_path) / "reports" / "latest" / f"{flow.name}.result.json"
        )
        stage_coverage_artifacts(repo_root_path, result, output)
        write_json(result, output)
        print(f"Wrote result: {output}")
        return 0
    except (ConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
