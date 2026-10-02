# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Derived JUnit XML: the structured-result guarantee for simulation leaves.

Framework-neutral rule: every graded simulation leaf except a skipped one ends with
xUnit XML at ``<leaf>/results/results.xml`` in the directory of its graded attempt. A
framework that writes its own (cocotb) is left untouched; otherwise (UVM leaves, a leaf
whose simulator died before the framework could write, or a leaf whose graded result
names no file, such as one the coordinator graded without a result of its own) the runner
synthesizes a single-testcase file from the already-classified ``StageResult``. A run that grades no leaf and whose aggregate status
is non-passing gets one run-level stage XML at ``<run>/results/results.xml`` so
pre-simulation failures stay visible to JUnit consumers.

Synthesized files are derived reporting artifacts: they are written strictly after
status classification, are never read back as parser evidence, and carry a suite-level
``producer`` property so native framework output can always be told apart from runner
output (and the functions here clean up only marked files).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .compat import UTC
from .models import Flow, StageResult
from .paths import repo_rel
from .results import aggregate_status, exit_code_for_status

PRODUCER = "run_dv.py junit-fallback"

# Order in which a leafless failing run picks the stage it reports, matching the
# aggregate-status precedence in `results.aggregate_status`.
_STAGE_STATUS_PRECEDENCE = ("ERROR", "TIMEOUT", "FAIL", "UNKNOWN")

_LEAF_STAGES = {"sim", "regress"}


def results_xml_path(leaf_dir: Path) -> Path:
    return leaf_dir / "results" / "results.xml"


def is_generated_junit(path: Path) -> bool:
    """True when `path` carries the synthesized-output producer marker."""
    try:
        root_elem = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return any(
        prop.get("name") == "producer" and prop.get("value") == PRODUCER
        for prop in root_elem.iter("property")
    )


def discard_generated_junit(path: Path) -> None:
    """Remove `path` when it carries the producer marker; a native file is left alone."""
    if path.is_file() and is_generated_junit(path):
        path.unlink()


def _rel(root: Path, path: Path | str | None) -> str:
    if path is None:
        return ""
    return repo_rel(root, path) or str(path)


def _failure_node(status: str, buckets: list[dict] | None) -> tuple[str, str | None]:
    """Map a non-PASS status to (element tag, type attribute).

    The type attribute reuses the canonical failure-bucket vocabulary so `result.json`
    and the XML never grow separate enums.
    """
    if status == "SKIP":
        return "skipped", None
    if status == "TIMEOUT":
        return "error", "timeout"
    if status == "UNKNOWN":
        return "error", "unknown"
    kinds = [
        str(bucket.get("kind"))
        for bucket in buckets or []
        if isinstance(bucket, dict) and bucket.get("kind")
    ]
    if status == "FAIL":
        return "failure", kinds[0] if kinds else "sim_failure"
    return "error", kinds[0] if kinds else "tool_error"


def _testcase(
    flow: Flow,
    result: StageResult,
    *,
    name: str,
    system_out: list[str],
) -> ET.Element:
    target = result.target or (result.metadata or {}).get("target") or "default"
    case = ET.Element(
        "testcase",
        {
            "classname": f"{flow.name}.{target}",
            "name": name,
            "time": f"{result.duration_sec:.3f}",
        },
    )
    if result.status != "PASS":
        tag, type_attr = _failure_node(result.status, result.failure_buckets)
        attrs = {"message": result.reason or result.status}
        if type_attr:
            attrs["type"] = type_attr
        ET.SubElement(case, tag, attrs)
    if system_out:
        out = ET.SubElement(case, "system-out")
        out.text = "\n".join(system_out)
    return case


def _result_lines(root: Path, result: StageResult, result_json: Path) -> list[str]:
    lines = []
    if result.log:
        lines.append(f"log: {result.log}")
    lines.append(f"result_json: {_rel(root, result_json)}")
    parser = result.parser or {}
    if parser.get("policy"):
        lines.append(f"parser_policy: {parser['policy']}")
    if parser.get("status_source"):
        lines.append(f"status_source: {parser['status_source']}")
    for bucket in result.failure_buckets or []:
        if isinstance(bucket, dict):
            lines.append(f"failure_bucket: {bucket.get('kind')}: {bucket.get('signature')}")
    attempt = (result.metadata or {}).get("attempt")
    if attempt is not None:
        lines.append(f"attempt: {attempt}")
    return lines


def _suites(
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    *,
    timestamp: str,
    cases: list[ET.Element],
    result_json: Path,
) -> ET.Element:
    counts = {
        "tests": str(len(cases)),
        "failures": str(sum(1 for case in cases if case.find("failure") is not None)),
        "errors": str(sum(1 for case in cases if case.find("error") is not None)),
        "skipped": str(sum(1 for case in cases if case.find("skipped") is not None)),
        "time": f"{sum(float(case.get('time', 0)) for case in cases):.3f}",
    }
    suites = ET.Element("testsuites", dict(counts))
    suite = ET.SubElement(
        suites,
        "testsuite",
        {"name": flow.name, "timestamp": timestamp, **counts},
    )
    properties = ET.SubElement(suite, "properties")
    for key, value in (
        ("producer", PRODUCER),
        ("generated_at", datetime.now(UTC).isoformat()),
        ("flow", flow.name),
        ("kind", flow.kind),
        ("framework", flow.framework),
        ("tool", tool),
        ("run_dir", _rel(root, run_dir)),
        ("result_json", _rel(root, result_json)),
    ):
        ET.SubElement(properties, "property", {"name": key, "value": value})
    suite.extend(cases)
    return suites


def _write_atomic(path: Path, suites: ET.Element) -> None:
    tree = ET.ElementTree(suites)
    ET.indent(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp"
    try:
        tree.write(tmp, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_leaf_junit(
    *,
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    result: StageResult,
    leaf_dir: Path,
    result_json: Path | None = None,
) -> Path | None:
    """Guarantee structured XML for one graded leaf; never touch a native file.

    `result_json` names the record that holds the grade, the leaf's own by default.
    Returns the synthesized path, or None when the framework already wrote one.
    """
    xml_path = results_xml_path(leaf_dir)
    if xml_path.exists():
        return None
    seed = (result.metadata or {}).get("seed")
    name = f"{result.item}[seed={seed}]" if seed is not None else str(result.item)
    leaf_json = result_json or leaf_dir / "result.json"
    case = _testcase(flow, result, name=name, system_out=_result_lines(root, result, leaf_json))
    suites = _suites(
        flow,
        root,
        run_dir,
        tool,
        timestamp=result.started_at or datetime.now(UTC).isoformat(),
        cases=[case],
        result_json=leaf_json,
    )
    _write_atomic(xml_path, suites)
    return xml_path


def materialize_interruption_junit(
    *,
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    interruption: dict,
    progress: dict,
) -> Path | None:
    """Run-level XML for a run that stopped before its planned leaves finished.

    The leaves that did finish keep their own files; this errored testcase is what stops a
    JUnit consumer from reading those alone as the whole run. A file without the producer
    marker is never touched.
    """
    run_xml = run_dir / "results" / "results.xml"
    if run_xml.is_file() and not is_generated_junit(run_xml):
        return None
    now = str(interruption.get("recorded_at") or datetime.now(UTC).isoformat())
    reason = (
        f"{interruption.get('reason') or 'run interrupted'}: "
        f"{progress.get('completed_count', 0)} of {progress.get('expected_count', 0)} "
        "planned leaves ran"
    )
    marker = StageResult(
        stage="run",
        item=None,
        status="ERROR",
        return_code=exit_code_for_status("ERROR"),
        duration_sec=0.0,
        started_at=now,
        ended_at=now,
        reason=reason,
        failure_buckets=[{"kind": "interruption", "signature": reason, "count": 1}],
    )
    case = _testcase(
        flow,
        marker,
        name="run",
        system_out=_result_lines(root, marker, run_dir / "result.json"),
    )
    suites = _suites(
        flow,
        root,
        run_dir,
        tool,
        timestamp=now,
        cases=[case],
        result_json=run_dir / "result.json",
    )
    _write_atomic(run_xml, suites)
    return run_xml


def _first_failing_stage(stages: list[StageResult]) -> StageResult | None:
    for status in _STAGE_STATUS_PRECEDENCE:
        for stage in stages:
            if stage.status == status:
                return stage
    return None


def materialize_stage_junit(
    *,
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    stages: list[StageResult],
) -> Path | None:
    """Run-level stage XML for a non-passing run that grades no leaf other than a skipped one.

    When gated off (a leaf was graded, the run passes, or structured XML already
    represents the run), a stale marked file from a previous invocation into the same
    run dir is removed; a file without the producer marker is never touched.
    """
    run_xml = run_dir / "results" / "results.xml"

    def _cleanup() -> None:
        if run_xml.is_file() and is_generated_junit(run_xml):
            run_xml.unlink()

    graded_leaf = any(
        stage.stage in _LEAF_STAGES and stage.item is not None and stage.status != "SKIP"
        for stage in stages
    )
    failing = _first_failing_stage(stages)
    if graded_leaf or failing is None or aggregate_status(stages) == "PASS":
        _cleanup()
        return None
    # Structured XML elsewhere in the run dir (leaf files from an earlier invocation)
    # already represents this run to JUnit consumers.
    if any(p != run_xml for p in run_dir.rglob("results/results.xml")):
        _cleanup()
        return None
    if run_xml.is_file() and not is_generated_junit(run_xml):
        return None

    case = _testcase(
        flow,
        failing,
        name=failing.stage,
        system_out=_result_lines(root, failing, run_dir / "result.json"),
    )
    suites = _suites(
        flow,
        root,
        run_dir,
        tool,
        timestamp=failing.started_at or datetime.now(UTC).isoformat(),
        cases=[case],
        result_json=run_dir / "result.json",
    )
    _write_atomic(run_xml, suites)
    failing.artifacts = dict(failing.artifacts or {})
    failing.artifacts["results_xml"] = _rel(root, run_xml)
    return run_xml
