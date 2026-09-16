# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Grading of a formal stage from tool evidence.

A formal item's status comes from what the backend wrote, never from its exit code alone:
the per-task status lines a `grader = "formal"` policy in `parsers.toml` matches in the stage
log, the `status` file and JUnit report in each task's work directory, or, for a backend
without a native summary, the summary file named by the app's `evidence` table. Missing
evidence grades UNKNOWN, an unreached cover grades FAIL, and a non-zero exit code with passing
evidence grades UNKNOWN.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import PLACEHOLDER_RE, as_str_list
from .logparse import ANSI_ESCAPE_RE, evidence_record, policy_fingerprint
from .models import StageResult
from .paths import repo_rel

# Run-level aggregation order; the first status present wins.
STATUS_PRECEDENCE = ("ERROR", "TIMEOUT", "FAIL", "UNKNOWN", "PASS")

# A task status outside the runner vocabulary (sby's CANCELLED) grades ERROR.
TASK_STATUS_MAP = {status: status for status in STATUS_PRECEDENCE}

BUCKET_BY_STATUS = {
    "FAIL": "formal_fail",
    "ERROR": "tool_error",
    "TIMEOUT": "timeout",
    "UNKNOWN": "unknown",
}

PROPERTY_COUNTERS = ("proven", "failed", "inconclusive", "covered", "unreached")

# Evidence-hook pattern lists and the property counter each match feeds.
EVIDENCE_HOOK_COUNTERS = {
    "pass_patterns": "proven",
    "fail_patterns": "failed",
    "inconclusive_patterns": "inconclusive",
    "cover_patterns": "covered",
    "unreached_patterns": "unreached",
}

# Evidence-record status for a summary line that fed a property counter.
_COUNTER_STATUS = {
    "proven": "PASS",
    "covered": "PASS",
    "failed": "FAIL",
    "unreached": "FAIL",
    "inconclusive": "UNKNOWN",
}

# sby task modes that check assertions, and the one that checks cover statements.
ASSERT_MODES = {"bmc", "prove", "live"}
COVER_MODE = "cover"

EVIDENCE_LIMIT = 25


@dataclass(frozen=True)
class FormalTask:
    """One backend task: an sby task work directory, or the single summary of an app."""

    name: str
    status: str
    return_code: int | None
    mode: str
    workdir: Path | None
    # Property id -> one of PROPERTY_COUNTERS.
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class FormalDecision:
    status: str
    reason: str
    evidence: list[dict[str, str]]
    failure_buckets: list[dict[str, Any]]
    parser: dict[str, Any]
    formal: dict[str, Any]


def formal_policy_for_tool(
    tool: str, simulators: dict[str, Any], policies: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """Return the formal grading policy the tool's registry entry names, or None."""
    tool_cfg = simulators.get(tool)
    if not isinstance(tool_cfg, dict):
        return None
    name = tool_cfg.get("parser_policy")
    if not name:
        return None
    policy = policies.get(str(name))
    if not isinstance(policy, dict) or policy.get("grader") != "formal":
        return None
    return str(name), policy


def render_evidence_path(template: str, *, run_dir: Path, item: str, cwd: Path) -> Path:
    """Render an evidence `summary` template; a relative result resolves against `cwd`."""
    values = {"run_dir": str(run_dir), "item": item, "cwd": str(cwd)}
    rendered = PLACEHOLDER_RE.sub(
        lambda match: values.get(match.group(1), match.group(0)), template
    )
    path = Path(rendered).expanduser()
    return path if path.is_absolute() else cwd / path


def _empty_counters() -> dict[str, int]:
    return {counter: 0 for counter in PROPERTY_COUNTERS}


def _worst_status(statuses: list[str]) -> str:
    for status in STATUS_PRECEDENCE:
        if status in statuses:
            return status
    return "PASS"


def _task_name(basename: str, item: str) -> str:
    prefix = f"{item}_"
    if basename.startswith(prefix) and len(basename) > len(prefix):
        return basename[len(prefix) :]
    return basename


def _read_task_mode(workdir: Path) -> str:
    config = workdir / "config.sby"
    if not config.is_file():
        return ""
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "mode":
            return parts[1]
    return ""


def _read_status_file(workdir: Path) -> tuple[str, int | None] | None:
    status_file = workdir / "status"
    if not status_file.is_file():
        return None
    parts = status_file.read_text(encoding="utf-8", errors="replace").split()
    if not parts:
        return None
    return_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return parts[0].upper(), return_code


def _property_status(testcase: ET.Element) -> str:
    if testcase.find("failure") is not None:
        return "FAIL"
    if testcase.find("error") is not None:
        return "ERROR"
    if testcase.find("skipped") is not None:
        return "UNKNOWN"
    return "PASS"


def _junit_properties(workdir: Path, mode: str, task_status: str) -> dict[str, str] | None:
    """Classify the properties of one sby task from its JUnit report.

    A task grades only the property kind its mode checks: assertions in `bmc`, `prove`, and
    `live`, cover statements in `cover`. A property FAIL counts as failed only inside a task
    whose status is FAIL: an induction counterexample in an UNKNOWN task is inconclusive.
    Returns None when the work directory holds no readable report.
    """
    reports = sorted(workdir.glob("*.xml"))
    if not reports:
        return None
    try:
        root_elem = ET.parse(reports[0]).getroot()
    except ET.ParseError:
        return None
    classified: dict[str, str] = {}
    for testcase in root_elem.iter("testcase"):
        kind = testcase.get("type", "")
        name = testcase.get("id") or testcase.get("name", "")
        if not kind or not name:
            continue
        status = _property_status(testcase)
        if kind == "ASSERT" and (not mode or mode in ASSERT_MODES):
            if status == "PASS":
                classified[name] = "proven"
            elif status == "FAIL" and task_status == "FAIL":
                classified[name] = "failed"
            else:
                classified[name] = "inconclusive"
        elif kind == "COVER" and (not mode or mode == COVER_MODE):
            classified[name] = "covered" if status == "PASS" else "unreached"
    return classified


# Lower rank wins when tasks disagree on one property.
_VERDICT_RANK = {"failed": 0, "inconclusive": 1, "proven": 2, "covered": 0, "unreached": 1}


def _merge_properties(tasks: list[FormalTask]) -> dict[str, int]:
    """Count each property once across tasks.

    An assertion is failed if any task failed it, else inconclusive if any task left it open,
    else proven. A cover statement is covered if any cover task reached it, else unreached.
    """
    merged: dict[str, str] = {}
    for task in tasks:
        for name, verdict in task.properties.items():
            current = merged.get(name)
            if current is None or _VERDICT_RANK[verdict] < _VERDICT_RANK[current]:
                merged[name] = verdict
    counters = _empty_counters()
    for verdict in merged.values():
        counters[verdict] += 1
    return counters


def _task_record(task: FormalTask, root: Path) -> dict[str, Any]:
    counters = _empty_counters()
    for verdict in task.properties.values():
        counters[verdict] += 1
    return {
        "name": task.name,
        "mode": task.mode,
        "status": task.status,
        "return_code": task.return_code,
        "workdir": repo_rel(root, task.workdir) if task.workdir is not None else None,
        **counters,
    }


def _buckets(status: str, reason: str, log_path: Path, root: Path) -> list[dict[str, Any]]:
    bucket = BUCKET_BY_STATUS.get(status)
    if bucket is None:
        return []
    example = repo_rel(root, log_path)
    return [
        {
            "kind": bucket,
            "signature": reason[:120],
            "count": 1,
            "examples": [example] if example else [],
        }
    ]


def _decision(
    *,
    policy_name: str,
    policy: dict[str, Any],
    status: str,
    reason: str,
    source: str,
    evidence: list[dict[str, str]],
    tasks: list[FormalTask],
    counters: dict[str, int],
    log_path: Path,
    root: Path,
) -> FormalDecision:
    parser = {
        "policy": policy_name,
        "policy_fingerprint": policy_fingerprint(policy),
        "positive_evidence_required": True,
        "status_source": source,
        "extensions": [],
        "evidence": evidence[:EVIDENCE_LIMIT],
    }
    formal = {
        "grader": policy_name,
        "tasks": [_task_record(task, root) for task in tasks],
        **counters,
    }
    return FormalDecision(
        status, reason, evidence, _buckets(status, reason, log_path, root), parser, formal
    )


def _match_lines(patterns: list[str], text: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            matches.append(match.group(0).strip() or pattern)
    return matches


def _locate_workdir(workdir_text: str, cwd: Path, stage_dir: Path) -> Path | None:
    """Resolve a logged work directory: as written (relative to the launch `cwd`), else by
    basename under the stage directory."""
    raw = Path(workdir_text)
    candidate = raw if raw.is_absolute() else cwd / raw
    if candidate.is_dir():
        return candidate
    if (stage_dir / raw.name).is_dir():
        return stage_dir / raw.name
    return None


def _log_tasks(
    policy: dict[str, Any], text: str, *, item: str, cwd: Path, stage_dir: Path
) -> dict[str, tuple[str, int | None, Path | None]]:
    """Map task basename -> (status, return code, work directory) from the log status lines."""
    found: dict[str, tuple[str, int | None, Path | None]] = {}
    for pattern in as_str_list(policy.get("task_status_patterns"), "task_status_patterns"):
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            groups = match.groupdict()
            status = str(groups.get("status") or "").upper()
            rc_text = groups.get("rc")
            return_code = int(rc_text) if rc_text and rc_text.isdigit() else None
            workdir_text = groups.get("workdir") or ""
            basename = Path(workdir_text).name if workdir_text else item
            workdir = _locate_workdir(workdir_text, cwd, stage_dir) if workdir_text else None
            found[basename] = (status, return_code, workdir)
    return found


def _discovered_workdirs(stage_dir: Path, item: str) -> dict[str, Path]:
    dirs: dict[str, Path] = {}
    for path in sorted(stage_dir.glob(f"{item}*")):
        if path.is_dir() and (path.name == item or path.name.startswith(f"{item}_")):
            if (path / "status").is_file():
                dirs[path.name] = path
    return dirs


def _collect_tasks(
    *,
    policy: dict[str, Any],
    text: str,
    root: Path,
    item: str,
    cwd: Path,
    stage_dir: Path,
    log_path: Path,
    evidence: list[dict[str, str]],
) -> list[FormalTask]:
    """Build one FormalTask per task seen in the log or found as a work directory.

    A logged status wins over the status file; when both exist and disagree the worse one
    stands. Property verdicts come from the JUnit report when the policy names `sby-junit`.
    """
    logged = _log_tasks(policy, text, item=item, cwd=cwd, stage_dir=stage_dir)
    workdirs = _discovered_workdirs(stage_dir, item)
    read_junit = str(policy.get("task_results", "none")) == "sby-junit"
    tasks: list[FormalTask] = []
    for basename in sorted(set(logged) | set(workdirs)):
        status, rc, workdir = logged.get(basename, ("", None, None))
        workdir = workdir or workdirs.get(basename)
        if status:
            evidence.append(
                evidence_record(
                    "task_status", log_path, root, status, f"task {basename}: {status} rc={rc}"
                )
            )
        file_status = _read_status_file(workdir) if workdir is not None else None
        if file_status is not None and workdir is not None:
            evidence.append(
                evidence_record(
                    "status_file",
                    workdir / "status",
                    root,
                    file_status[0],
                    f"task {basename}: status file {file_status[0]}",
                )
            )
            if not status:
                status, rc = file_status
            elif file_status[0] != status:
                status = _worst_status([status, file_status[0]])
        status = TASK_STATUS_MAP.get(status, "ERROR")
        mode = _read_task_mode(workdir) if workdir is not None else ""
        properties: dict[str, str] | None = None
        if workdir is not None and read_junit:
            properties = _junit_properties(workdir, mode, status)
            if properties is None:
                evidence.append(
                    evidence_record(
                        "task_results",
                        workdir,
                        root,
                        "UNKNOWN",
                        f"task {basename}: no JUnit report",
                    )
                )
        tasks.append(
            FormalTask(
                name=_task_name(basename, item),
                status=status,
                return_code=rc,
                mode=mode,
                workdir=workdir,
                properties=properties or {},
            )
        )
    return tasks


def _grade_from_task_evidence(
    *,
    policy_name: str,
    policy: dict[str, Any],
    root: Path,
    item: str,
    cwd: Path,
    stage_dir: Path,
    log_path: Path,
    return_code: int,
) -> FormalDecision:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if bool(policy.get("strip_ansi", True)):
        text = ANSI_ESCAPE_RE.sub("", text)
    evidence: list[dict[str, str]] = []

    hard_fail = _match_lines(as_str_list(policy.get("hard_fail_patterns"), "hard_fail"), text)
    for line in hard_fail[:10]:
        evidence.append(evidence_record("hard_fail_pattern", log_path, root, "ERROR", line))
    tasks = _collect_tasks(
        policy=policy,
        text=text,
        root=root,
        item=item,
        cwd=cwd,
        stage_dir=stage_dir,
        log_path=log_path,
        evidence=evidence,
    )
    for line in _match_lines(as_str_list(policy.get("evidence_patterns"), "evidence"), text)[:10]:
        evidence.append(evidence_record("log_pattern", log_path, root, "INFO", line))

    counters = _merge_properties(tasks)

    def decide(status: str, reason: str, source: str) -> FormalDecision:
        return _decision(
            policy_name=policy_name,
            policy=policy,
            status=status,
            reason=reason,
            source=source,
            evidence=evidence,
            tasks=tasks,
            counters=counters,
            log_path=log_path,
            root=root,
        )

    if hard_fail:
        return decide("ERROR", f"hard-fail pattern matched: {hard_fail[0]}", "log_pattern")
    if not tasks:
        evidence.append(
            evidence_record(
                "task_status", log_path, root, "UNKNOWN", "no task status line or status file"
            )
        )
        return decide(
            "UNKNOWN",
            f"no formal task evidence found (process exited {return_code})",
            "task_status",
        )
    status = _worst_status([task.status for task in tasks])
    if status != "PASS":
        names = ", ".join(f"{task.name} {task.status}" for task in tasks if task.status != "PASS")
        return decide(status, f"formal task(s) not passing: {names}", "task_status")
    if counters["unreached"]:
        return decide(
            "FAIL", f"{counters['unreached']} cover statement(s) unreached", "task_results"
        )
    if return_code != 0:
        evidence.append(
            evidence_record(
                "return_code", log_path, root, "UNKNOWN", f"process exited {return_code}"
            )
        )
        return decide(
            "UNKNOWN", f"process exited {return_code} with passing task evidence", "return_code"
        )
    return decide(
        "PASS",
        f"{len(tasks)} formal task(s) passed; {counters['proven']} proven, "
        f"{counters['covered']} covered",
        "task_status",
    )


def _grade_from_summary_file(
    *,
    app_name: str,
    hook: dict[str, Any],
    root: Path,
    item: str,
    cwd: Path,
    run_dir: Path,
    log_path: Path,
    return_code: int,
) -> FormalDecision:
    policy_name = f"evidence:{app_name}"
    summary = render_evidence_path(str(hook["summary"]), run_dir=run_dir, item=item, cwd=cwd)
    evidence: list[dict[str, str]] = []
    counters = _empty_counters()

    def decide(status: str, reason: str) -> FormalDecision:
        return _decision(
            policy_name=policy_name,
            policy=hook,
            status=status,
            reason=reason,
            source="summary_file",
            evidence=evidence,
            tasks=[FormalTask(app_name, status, return_code, "", None)],
            counters=counters,
            log_path=log_path,
            root=root,
        )

    if not summary.is_file() or summary.stat().st_size == 0:
        evidence.append(
            evidence_record(
                "summary_file", summary, root, "UNKNOWN", "summary file missing or empty"
            )
        )
        return decide("UNKNOWN", f"formal summary file missing or empty: {repo_rel(root, summary)}")
    text = summary.read_text(encoding="utf-8", errors="replace")
    first: dict[str, str] = {}
    for key, counter in EVIDENCE_HOOK_COUNTERS.items():
        matches = _match_lines(as_str_list(hook.get(key), key), text)
        counters[counter] = len(matches)
        if matches:
            first[counter] = matches[0]
            for line in matches[:5]:
                evidence.append(
                    evidence_record("summary_file", summary, root, _COUNTER_STATUS[counter], line)
                )
    if counters["failed"] or counters["unreached"]:
        return decide(
            "FAIL",
            f"{counters['failed']} failed, {counters['unreached']} unreached: "
            f"{first.get('failed') or first.get('unreached')}",
        )
    if counters["inconclusive"]:
        return decide(
            "UNKNOWN", f"{counters['inconclusive']} inconclusive: {first['inconclusive']}"
        )
    if not counters["proven"] and not counters["covered"]:
        return decide("UNKNOWN", f"no pass evidence in summary file {repo_rel(root, summary)}")
    if return_code != 0:
        return decide("UNKNOWN", f"process exited {return_code} with passing summary evidence")
    return decide("PASS", f"{counters['proven']} proven, {counters['covered']} covered")


def grade_formal_stage(
    *,
    root: Path,
    tool: str,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    item: str,
    app_name: str,
    app_table: dict[str, Any],
    cwd: Path,
    stage_dir: Path,
    run_dir: Path,
    log_path: Path,
    return_code: int,
) -> FormalDecision:
    """Grade one formal item from its evidence.

    The app's `evidence` table wins over the tool's `parser_policy`; with neither the item is
    UNKNOWN.
    """
    hook = app_table.get("evidence")
    if isinstance(hook, dict):
        return _grade_from_summary_file(
            app_name=app_name,
            hook=hook,
            root=root,
            item=item,
            cwd=cwd,
            run_dir=run_dir,
            log_path=log_path,
            return_code=return_code,
        )
    selected = formal_policy_for_tool(tool, simulators, policies)
    if selected is None:
        reason = (
            f"no grading source: tool `{tool}` names no formal `parser_policy` and app "
            f"`{app_name}` sets no `evidence` table"
        )
        evidence = [evidence_record("task_status", log_path, root, "UNKNOWN", reason)]
        return _decision(
            policy_name="none",
            policy={},
            status="UNKNOWN",
            reason=reason,
            source="none",
            evidence=evidence,
            tasks=[],
            counters=_empty_counters(),
            log_path=log_path,
            root=root,
        )
    policy_name, policy = selected
    return _grade_from_task_evidence(
        policy_name=policy_name,
        policy=policy,
        root=root,
        item=item,
        cwd=cwd,
        stage_dir=stage_dir,
        log_path=log_path,
        return_code=return_code,
    )


def formal_summary(stages: list[StageResult]) -> dict[str, Any]:
    """Run-level proof totals: property counters summed over the graded formal stages."""
    counters = _empty_counters()
    total = passing = 0
    for stage in stages:
        report = stage.formal
        if not isinstance(report, dict):
            continue
        for counter in PROPERTY_COUNTERS:
            counters[counter] += int(report.get(counter) or 0)
        for task in report.get("tasks") or []:
            total += 1
            if task.get("status") == "PASS":
                passing += 1
    return {
        **counters,
        "tasks": {"total": total, "passing": passing, "failing": total - passing},
    }
