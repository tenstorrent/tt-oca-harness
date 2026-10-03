# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Derived JUnit XML: the structured-result guarantee for simulation leaves.

Framework-neutral rule: every graded simulation leaf except a skipped one ends with
xUnit XML at ``<leaf>/results/results.xml`` in the directory of its graded attempt. A
framework that writes its own (cocotb) is left untouched; otherwise (UVM leaves, a leaf
whose simulator died before the framework could write, or a leaf whose graded result
names no file, such as one the coordinator graded without a result of its own) the runner
synthesizes a single-testcase file from the already-classified ``StageResult``. When the
graded status is FAIL, ERROR, TIMEOUT or UNKNOWN and the framework's file records no
failure or error node, or does not parse, the runner also writes
``<leaf>/results/graded.xml``, the same single-testcase file, beside it. A run that grades
no leaf and whose aggregate status is non-passing gets one run-level stage XML at
``<run>/results/results.xml`` so pre-simulation failures stay visible to JUnit consumers.

Synthesized files are derived reporting artifacts: they are written strictly after
status classification, are never read back as parser evidence, and carry a suite-level
``producer`` property so native framework output can always be told apart from runner
output (and the functions here clean up only marked files).

The report file is the one a CI system publishes: every graded simulation leaf also gets
``<leaf>/report/junit.xml``, one testcase named by its testlist entry rather than by the
framework's module and function, with the failure message and the end of the leaf log. A
run whose run-level file above is written gets the same case in ``<run>/report/junit.xml``.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC
from .logparse import ANSI_ESCAPE_RE
from .models import Flow, StageResult
from .paths import repo_rel
from .results import NON_PASS_STATUSES, aggregate_status, exit_code_for_status

PRODUCER = "run_dv.py junit-fallback"

# Prefix that turns a repo-relative log path into a link in the report, such as the URL a CI
# job serves its archived run tree from.
LOG_URL_BASE = os.environ.get("OCAH_DV_LOG_URL_BASE", "")

# A non-passing report case carries at most this many log lines, taken from at most this many
# trailing bytes of the log, and at most this many failure messages.
REPORT_TAIL_LINES = 200
REPORT_TAIL_BYTES = 64 * 1024
REPORT_MESSAGE_LIMIT = 20

# Code points XML 1.0 cannot carry.
_XML_INVALID_RE = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")

# Order in which a leafless failing run picks the stage it reports, matching the
# aggregate-status precedence in `results.aggregate_status`.
_STAGE_STATUS_PRECEDENCE = ("ERROR", "TIMEOUT", "FAIL", "UNKNOWN")

_LEAF_STAGES = {"sim", "regress"}


def results_xml_path(leaf_dir: Path) -> Path:
    return leaf_dir / "results" / "results.xml"


def graded_xml_path(leaf_dir: Path) -> Path:
    return leaf_dir / "results" / "graded.xml"


def report_xml_path(directory: Path) -> Path:
    return directory / "report" / "junit.xml"


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


def _records_a_failure(path: Path) -> bool:
    """True when `path` parses and holds a failure or error node."""
    try:
        root_elem = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return any(elem.tag in {"failure", "error"} for elem in root_elem.iter())


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


def _xml_text(text: str) -> str:
    """`text` without terminal escape sequences or code points XML 1.0 cannot carry."""
    return _XML_INVALID_RE.sub("", ANSI_ESCAPE_RE.sub("", text))


def _target(result: StageResult) -> str:
    return result.target or (result.metadata or {}).get("target") or "default"


def _testcase(
    flow: Flow,
    result: StageResult,
    *,
    name: str,
    system_out: list[str],
    classname: str | None = None,
    failures: Sequence[str] = (),
) -> ET.Element:
    """One testcase; `failures` supplies the failure node's message and its text when given."""
    case = ET.Element(
        "testcase",
        {
            "classname": classname or f"{flow.name}.{_target(result)}",
            "name": name,
            "time": f"{result.duration_sec:.3f}",
        },
    )
    if result.status != "PASS":
        tag, type_attr = _failure_node(result.status, result.failure_buckets)
        attrs = {"message": _xml_text(failures[0] if failures else result.reason or result.status)}
        if type_attr:
            attrs["type"] = type_attr
        node = ET.SubElement(case, tag, attrs)
        if failures:
            lines = dict.fromkeys(line for line in (result.reason, *failures) if line)
            node.text = _xml_text("\n".join(lines))
    if system_out:
        out = ET.SubElement(case, "system-out")
        out.text = _xml_text("\n".join(system_out))
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
    _write_atomic(xml_path, _leaf_suites(flow, root, run_dir, tool, result, leaf_dir, result_json))
    return xml_path


def ensure_graded_junit(
    *,
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    result: StageResult,
    leaf_dir: Path,
    result_json: Path | None = None,
) -> Path | None:
    """Publish a non-passing grade beside a framework file that reads as a pass.

    Writes `results/graded.xml` when `results/results.xml` is the framework's own, the
    graded status is FAIL, ERROR, TIMEOUT or UNKNOWN, and that file records no failure or
    error node or does not parse; otherwise removes a marked `graded.xml`. The framework's
    file is never touched, and a `graded.xml` without the marker is left alone. Returns the
    written path, or None.
    """
    xml_path = results_xml_path(leaf_dir)
    graded_path = graded_xml_path(leaf_dir)
    native = xml_path.is_file() and not is_generated_junit(xml_path)
    if not native or result.status not in NON_PASS_STATUSES or _records_a_failure(xml_path):
        discard_generated_junit(graded_path)
        return None
    if graded_path.exists() and not is_generated_junit(graded_path):
        return None
    suites = _leaf_suites(flow, root, run_dir, tool, result, leaf_dir, result_json)
    _write_atomic(graded_path, suites)
    return graded_path


def _leaf_suites(
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    result: StageResult,
    leaf_dir: Path,
    result_json: Path | None,
) -> ET.Element:
    seed = (result.metadata or {}).get("seed")
    name = f"{result.item}[seed={seed}]" if seed is not None else str(result.item)
    leaf_json = result_json or leaf_dir / "result.json"
    case = _testcase(flow, result, name=name, system_out=_result_lines(root, result, leaf_json))
    return _suites(
        flow,
        root,
        run_dir,
        tool,
        timestamp=result.started_at or datetime.now(UTC).isoformat(),
        cases=[case],
        result_json=leaf_json,
    )


def report_case_names(leaves: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """The report case name of each planned leaf, by leaf id.

    A test planned once in a stage is named by its testlist entry. A test planned with several
    seeds is named `<test>[<index>]`, the index counting its seeds in plan order, so a case
    keeps its name across runs whose seeds differ.
    """
    planned = list(leaves)
    counts = Counter((leaf["stage"], leaf["item"]) for leaf in planned)
    seen: Counter[tuple[Any, Any]] = Counter()
    names: dict[int, str] = {}
    for leaf in planned:
        key = (leaf["stage"], leaf["item"])
        item = str(leaf["item"])
        names[int(leaf["id"])] = item if counts[key] == 1 else f"{item}[{seen[key]}]"
        seen[key] += 1
    return names


def _log_tail(path: Path) -> list[str]:
    """The last `REPORT_TAIL_LINES` whole lines in the last `REPORT_TAIL_BYTES` of `path`.

    Returns [] when the file cannot be read.
    """
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - REPORT_TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if size > REPORT_TAIL_BYTES:
        # The window starts part-way through its first line.
        lines = lines[1:]
    return lines[-REPORT_TAIL_LINES:]


def _report_lines(root: Path, result: StageResult, result_json: Path) -> list[str]:
    seed = (result.metadata or {}).get("seed")
    lines = [f"seed: {seed}"] if seed is not None else []
    lines.extend(_result_lines(root, result, result_json))
    if not result.log:
        return lines
    if LOG_URL_BASE and not Path(result.log).is_absolute():
        lines.append(f"log_url: {LOG_URL_BASE}{result.log}")
    tail = _log_tail(root / result.log) if result.status != "PASS" else []
    if tail:
        lines.extend(["", f"last {len(tail)} lines of {result.log}:", *tail])
    return lines


def write_report_junit(
    *,
    flow: Flow,
    root: Path,
    run_dir: Path,
    tool: str,
    result: StageResult,
    directory: Path,
    name: str,
    result_json: Path,
    failures: Sequence[str] = (),
) -> Path | None:
    """Write `result` as the one testcase of `report/junit.xml` under `directory`.

    The case is `<flow>.<framework>.<target>` / `name`. A non-passing case takes its message
    from the first of `failures`, or from the graded reason when there are none, and its
    `system-out` ends with the tail of the log. A file at that path without the producer
    marker is left alone. Returns the written path, or None.
    """
    path = report_xml_path(directory)
    if path.exists() and not is_generated_junit(path):
        return None
    classname = ".".join(part for part in (flow.name, flow.framework, _target(result)) if part)
    case = _testcase(
        flow,
        result,
        name=name,
        system_out=_report_lines(root, result, result_json),
        classname=classname,
        failures=failures[:REPORT_MESSAGE_LIMIT],
    )
    suites = _suites(
        flow,
        root,
        run_dir,
        tool,
        timestamp=result.started_at or datetime.now(UTC).isoformat(),
        cases=[case],
        result_json=result_json,
    )
    _write_atomic(path, suites)
    return path


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
    JUnit consumer from reading those alone as the whole run. The run's report file carries
    the same case. A file without the producer marker is never touched.
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
    write_report_junit(
        flow=flow,
        root=root,
        run_dir=run_dir,
        tool=tool,
        result=marker,
        directory=run_dir,
        name="run",
        result_json=run_dir / "result.json",
    )
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

    The run's report file carries the same case, with the tail of the stage's log. When
    gated off (a leaf was graded, the run passes, or structured XML already represents the
    run), stale marked files from a previous invocation into the same run dir are removed;
    a file without the producer marker is never touched.
    """
    run_xml = run_dir / "results" / "results.xml"

    def _cleanup() -> None:
        discard_generated_junit(run_xml)
        discard_generated_junit(report_xml_path(run_dir))

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
    write_report_junit(
        flow=flow,
        root=root,
        run_dir=run_dir,
        tool=tool,
        result=failing,
        directory=run_dir,
        name=failing.stage,
        result_json=run_dir / "result.json",
    )
    failing.artifacts = dict(failing.artifacts or {})
    failing.artifacts["results_xml"] = _rel(root, run_xml)
    return run_xml
