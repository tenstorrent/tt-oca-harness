# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""PASS/FAIL parser policy handling for native DV runs."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .config import as_str_list, load_toml
from .models import ConfigError, Flow, ParserDecision
from .paths import configs_root, repo_rel

FRAMEWORK_DEFAULT_POLICY = {
    "cocotb": "cocotb-default",
    "uvm": "uvm-log",
    "systemverilog": "generic-regex",
    "acceptance": "generic-regex",
}

PARSER_LIST_KEYS = (
    "structured_results",
    "summary_patterns",
    "pass_patterns",
    "fail_patterns",
    "ignore_patterns",
    "required_patterns",
    "hard_fail_patterns",
)

FLOW_PARSER_EXTENSION_KEYS = {
    "extra_pass_patterns": "pass_patterns",
    "extra_fail_patterns": "fail_patterns",
    "extra_ignore_patterns": "ignore_patterns",
    "extra_required_patterns": "required_patterns",
    "extra_hard_fail_patterns": "hard_fail_patterns",
    "extra_summary_patterns": "summary_patterns",
    "extra_structured_results": "structured_results",
}

SIMULATOR_PARSER_EXTENSION_KEYS = {
    "extra_fail_patterns": "fail_patterns",
    "extra_hard_fail_patterns": "hard_fail_patterns",
}

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# A `grader = "formal"` policy grades a formal stage from per-task status lines instead of
# simulation pass/fail evidence; `runlib.formal` applies it.
FORMAL_POLICY_KEYS = {
    "grader",
    "strip_ansi",
    "task_status_patterns",
    "task_results",
    "evidence_patterns",
    "hard_fail_patterns",
}
FORMAL_POLICY_LIST_KEYS = ("task_status_patterns", "evidence_patterns", "hard_fail_patterns")
FORMAL_TASK_RESULT_FORMATS = {"sby-junit", "none"}


def load_parser_registry(root: Path) -> dict[str, Any]:
    path = configs_root(root) / "parsers.toml"
    if not path.is_file():
        raise ConfigError(f"missing parser registry: {path}")
    data = load_toml(path)
    policies = data.get("policy", {})
    if not isinstance(policies, dict) or not policies:
        raise ConfigError(f"{path}: missing [policy.<name>] parser definitions")
    return policies


def parser_policy_name(flow: Flow) -> str:
    pass_fail = flow.raw.get("pass_fail", {})
    if isinstance(pass_fail, dict) and pass_fail.get("policy"):
        return str(pass_fail["policy"])
    return FRAMEWORK_DEFAULT_POLICY.get(flow.framework, "generic-regex")


def _compile_regex(pattern: str, source: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(f"{source}: invalid regex `{pattern}`: {exc}") from exc


def is_formal_policy(policy: Any) -> bool:
    return isinstance(policy, dict) and policy.get("grader") == "formal"


def validate_formal_policy(name: str, policy: dict[str, Any]) -> None:
    """Check a `grader = "formal"` policy: its keys, its patterns, and the `status` group."""
    where = f"parsers.toml policy `{name}`"
    if policy.get("grader") != "formal":
        raise ConfigError(f'{where}: `grader` must be "formal"')
    unknown = sorted(set(policy) - FORMAL_POLICY_KEYS)
    if unknown:
        raise ConfigError(f"{where}: unsupported key(s) for a formal grader: {', '.join(unknown)}")
    if not isinstance(policy.get("strip_ansi", True), bool):
        raise ConfigError(f"{where}: strip_ansi must be bool")
    if str(policy.get("task_results", "none")) not in FORMAL_TASK_RESULT_FORMATS:
        raise ConfigError(
            f"{where}: task_results must be one of {', '.join(sorted(FORMAL_TASK_RESULT_FORMATS))}"
        )
    for key in FORMAL_POLICY_LIST_KEYS:
        for pattern in as_str_list(policy.get(key), f"policy.{name}.{key}"):
            _compile_regex(pattern, where)
    task_patterns = as_str_list(policy.get("task_status_patterns"), f"policy.{name}")
    if not task_patterns:
        raise ConfigError(f"{where}: task_status_patterns must list at least one pattern")
    for pattern in task_patterns:
        if "status" not in re.compile(pattern).groupindex:
            raise ConfigError(
                f"{where}: task_status_patterns entry `{pattern}` needs a (?P<status>...) group"
            )


def validate_formal_grading_sources(
    flow: Flow, simulators: dict[str, Any], policies: dict[str, Any]
) -> None:
    """Every formal app backend needs a grading source: an `evidence` table on the app, or a
    formal `parser_policy` on the tool's registry entry."""
    graded_tools: set[str] = set()
    for tool in flow.tools:
        tool_cfg = simulators.get(tool, {})
        name = tool_cfg.get("parser_policy") if isinstance(tool_cfg, dict) else None
        if name is None:
            continue
        if not is_formal_policy(policies.get(str(name))):
            raise ConfigError(
                f"simulators.toml: [{tool}].parser_policy `{name}` is not a "
                f'`grader = "formal"` policy in parsers.toml'
            )
        graded_tools.add(tool)
    formal = flow.raw.get("formal", {})
    apps = formal.get("apps", {}) if isinstance(formal, dict) else {}
    if not isinstance(apps, dict):
        return
    for app_name, app in apps.items():
        if not isinstance(app, dict):
            continue
        for tool, table in app.items():
            if not isinstance(table, dict) or "evidence" in table or tool in graded_tools:
                continue
            raise ConfigError(
                f"{flow.path} [formal.apps.{app_name}.{tool}]: no grading source; the `{tool}` "
                "registry entry names no formal `parser_policy` and the app sets no `evidence` "
                "table"
            )


def validate_parser_registry(root: Path) -> dict[str, Any]:
    policies = load_parser_registry(root)
    for name, policy in policies.items():
        if not isinstance(policy, dict):
            raise ConfigError(f"parsers.toml: [policy.{name}] must be a table")
        if "grader" in policy:
            validate_formal_policy(name, policy)
            continue
        if not isinstance(policy.get("require_positive_evidence", True), bool):
            raise ConfigError(
                f"parsers.toml: policy `{name}` require_positive_evidence must be bool"
            )
        if str(policy.get("structured_format", "none")) not in {"xunit", "junit", "none"}:
            raise ConfigError(f"parsers.toml: policy `{name}` structured_format is unsupported")
        for key in PARSER_LIST_KEYS:
            values = as_str_list(policy.get(key), f"policy.{name}.{key}")
            if key.endswith("_patterns"):
                for pattern in values:
                    _compile_regex(pattern, f"parsers.toml policy `{name}`")
    return policies


def validate_parser_extensions(
    flow: Flow, simulators: dict[str, Any], policies: dict[str, Any]
) -> None:
    if flow.framework == "formal":
        validate_formal_grading_sources(flow, simulators, policies)
        return
    policy_name = parser_policy_name(flow)
    if policy_name not in policies:
        raise ConfigError(f"{flow.path}: parser policy `{policy_name}` missing from parsers.toml")

    pass_fail = flow.raw.get("pass_fail", {})
    if pass_fail is not None and not isinstance(pass_fail, dict):
        raise ConfigError(f"{flow.path}: [pass_fail] must be a table")
    pass_fail = pass_fail if isinstance(pass_fail, dict) else {}
    for key, value in pass_fail.items():
        if key == "policy":
            continue
        if key.startswith("replace_"):
            raise ConfigError(
                f"{flow.path}: `{key}` weakens parser policy; use additive extra_* keys"
            )
        if key not in FLOW_PARSER_EXTENSION_KEYS:
            raise ConfigError(f"{flow.path}: unsupported [pass_fail] key `{key}`")
        for pattern in as_str_list(value, f"pass_fail.{key}"):
            if "patterns" in key:
                _compile_regex(pattern, f"{flow.path} pass_fail.{key}")

    policy = policies[policy_name]
    if policy_name == "generic-regex":
        positive_sources = (
            as_str_list(policy.get("structured_results"), "generic-regex.structured_results")
            or as_str_list(policy.get("summary_patterns"), "generic-regex.summary_patterns")
            or as_str_list(policy.get("pass_patterns"), "generic-regex.pass_patterns")
            or as_str_list(
                pass_fail.get("extra_structured_results"), "pass_fail.extra_structured_results"
            )
            or as_str_list(
                pass_fail.get("extra_summary_patterns"), "pass_fail.extra_summary_patterns"
            )
            or as_str_list(pass_fail.get("extra_pass_patterns"), "pass_fail.extra_pass_patterns")
        )
        if not positive_sources:
            raise ConfigError(f"{flow.path}: generic-regex parser requires positive pass evidence")

    for tool in flow.tools:
        tool_cfg = simulators.get(tool, {})
        extensions = tool_cfg.get("parser_extensions", {}) if isinstance(tool_cfg, dict) else {}
        if extensions is None:
            continue
        if not isinstance(extensions, dict):
            raise ConfigError(f"simulators.toml: [{tool}.parser_extensions] must be a table")
        for key, value in extensions.items():
            if key not in SIMULATOR_PARSER_EXTENSION_KEYS:
                raise ConfigError(
                    f"simulators.toml: unsupported [{tool}.parser_extensions] key `{key}`"
                )
            for pattern in as_str_list(value, f"{tool}.parser_extensions.{key}"):
                _compile_regex(pattern, f"simulators.toml {tool}.parser_extensions.{key}")


def resolved_parser_policy(
    flow: Flow,
    tool: str,
    policies: dict[str, Any],
    simulators: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    policy_name = parser_policy_name(flow)
    base = policies.get(policy_name)
    if not isinstance(base, dict):
        raise ConfigError(f"{flow.path}: parser policy `{policy_name}` missing from parsers.toml")
    if "grader" in base:
        raise ConfigError(
            f"{flow.path}: parser policy `{policy_name}` is a formal grader, not a simulation policy"
        )

    effective: dict[str, Any] = {
        "require_positive_evidence": bool(base.get("require_positive_evidence", True)),
        "strip_ansi": bool(base.get("strip_ansi", True)),
        "structured_format": str(base.get("structured_format", "none")),
    }
    for key in PARSER_LIST_KEYS:
        effective[key] = as_str_list(base.get(key), f"policy.{policy_name}.{key}")

    extensions: list[str] = []
    pass_fail = flow.raw.get("pass_fail", {})
    if isinstance(pass_fail, dict):
        for src_key, dst_key in FLOW_PARSER_EXTENSION_KEYS.items():
            values = as_str_list(pass_fail.get(src_key), f"pass_fail.{src_key}")
            if values:
                effective[dst_key].extend(values)
        if any(key.startswith("extra_") for key in pass_fail):
            extensions.append(f"flow:{flow.name}")

    tool_cfg = simulators.get(tool, {})
    sim_ext = tool_cfg.get("parser_extensions", {}) if isinstance(tool_cfg, dict) else {}
    if isinstance(sim_ext, dict):
        for src_key, dst_key in SIMULATOR_PARSER_EXTENSION_KEYS.items():
            values = as_str_list(sim_ext.get(src_key), f"{tool}.parser_extensions.{src_key}")
            if values:
                effective[dst_key].extend(values)
        if any(key in sim_ext for key in SIMULATOR_PARSER_EXTENSION_KEYS):
            extensions.append(f"simulator:{tool}")

    return policy_name, effective, extensions


def evidence_record(kind: str, path: Path, root: Path, status: str, message: str) -> dict[str, str]:
    return {
        "kind": kind,
        "path": repo_rel(root, path) or str(path),
        "status": status,
        "message": message,
    }


def parse_xunit_result(path: Path, root: Path) -> tuple[str, dict[str, str]]:
    if not path.is_file():
        return "UNKNOWN", evidence_record(
            "results_xml", path, root, "UNKNOWN", "structured result missing"
        )
    if path.stat().st_size == 0:
        return "UNKNOWN", evidence_record(
            "results_xml", path, root, "UNKNOWN", "structured result is empty"
        )
    try:
        root_elem = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return "UNKNOWN", evidence_record(
            "results_xml", path, root, "UNKNOWN", f"malformed XML: {exc}"
        )

    total = len(root_elem.findall(".//testcase"))
    failing = len(root_elem.findall(".//failure")) + len(root_elem.findall(".//error"))
    if total == 0:
        return "UNKNOWN", evidence_record(
            "results_xml", path, root, "UNKNOWN", "0 testcase(s) found"
        )
    if failing:
        return "FAIL", evidence_record(
            "results_xml", path, root, "FAIL", f"{failing} testcase failure/error node(s)"
        )
    return "PASS", evidence_record("results_xml", path, root, "PASS", f"{total} testcase(s) passed")


def xunit_failure_messages(path: Path, *, limit: int = 8, width: int = 400) -> list[str]:
    """The message of every failure/error node in a JUnit file, first line only.

    cocotb writes the assertion text as `error_msg`; JUnit proper uses `message`; a node
    with neither carries it as text. Returns [] for a missing or malformed file.
    """
    if not path.is_file():
        return []
    try:
        root_elem = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    messages: list[str] = []
    for node in [*root_elem.iter("failure"), *root_elem.iter("error")]:
        text = node.get("message") or node.get("error_msg") or (node.text or "")
        first = text.strip().splitlines()[0].strip() if text.strip() else ""
        if first:
            messages.append(first[:width])
        if len(messages) >= limit:
            break
    return messages


def _match_lines(patterns: list[str], text: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.MULTILINE):
            matches.append(match.group(0).strip() or pattern)
    return matches


def _is_ignored(line: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, line, flags=re.MULTILINE) for pattern in patterns)


def _summary_evidence(
    pattern: str, match: re.Match[str], log_path: Path, root: Path
) -> dict[str, str]:
    numbers = {
        key: int(value)
        for key, value in match.groupdict().items()
        if value is not None and str(value).isdigit()
    }
    message = match.group(0).strip()

    if {"tests", "pass", "fail", "skip"}.issubset(numbers):
        status = (
            "PASS"
            if numbers["tests"] > 0
            and numbers["fail"] == 0
            and numbers["pass"] + numbers["skip"] == numbers["tests"]
            else "FAIL"
        )
        return evidence_record("log_summary", log_path, root, status, message)

    if "uvm_error" in numbers or "uvm_fatal" in numbers:
        status = (
            "PASS"
            if numbers.get("uvm_error", 0) == 0 and numbers.get("uvm_fatal", 0) == 0
            else "FAIL"
        )
        return evidence_record("log_summary", log_path, root, status, message)

    return evidence_record("log_summary", log_path, root, "PASS", message or pattern)


def policy_fingerprint(policy: dict[str, Any]) -> str:
    payload = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _decision(
    policy_name: str,
    policy: dict[str, Any],
    extensions: list[str],
    status: str,
    reason: str,
    source: str,
    evidence: list[dict[str, str]],
    bucket: str | None,
) -> ParserDecision:
    parser = {
        "policy": policy_name,
        "policy_fingerprint": policy_fingerprint(policy),
        "positive_evidence_required": bool(policy["require_positive_evidence"]),
        "status_source": source,
        "extensions": extensions,
        "evidence": evidence[:25],
    }
    failure_buckets = []
    if bucket:
        failure_buckets = [{"kind": bucket, "signature": reason[:120], "count": 1, "examples": []}]
    return ParserDecision(status, reason, evidence, failure_buckets, parser)


def parse_stage_result(
    *,
    flow: Flow,
    tool: str,
    policies: dict[str, Any],
    simulators: dict[str, Any],
    root: Path,
    log_path: Path,
    results_dir: Path,
    return_code: int,
) -> ParserDecision:
    policy_name, policy, extensions = resolved_parser_policy(flow, tool, policies, simulators)
    text = log_path.read_text(errors="replace") if log_path.is_file() else ""
    if policy["strip_ansi"]:
        text = ANSI_ESCAPE_RE.sub("", text)

    evidence: list[dict[str, str]] = []
    positive = False
    structured_unknown = False

    for result_name in policy["structured_results"]:
        structured_status, record = parse_xunit_result(results_dir / result_name, root)
        evidence.append(record)
        if structured_status == "FAIL":
            return _decision(
                policy_name,
                policy,
                extensions,
                "FAIL",
                record["message"],
                "structured_result",
                evidence,
                "sim_failure",
            )
        if structured_status == "PASS":
            positive = True
        else:
            structured_unknown = True

    hard_fail_matches = _match_lines(policy["hard_fail_patterns"], text)
    if hard_fail_matches:
        for line in hard_fail_matches[:10]:
            evidence.append(evidence_record("hard_fail_pattern", log_path, root, "ERROR", line))
        return _decision(
            policy_name,
            policy,
            extensions,
            "ERROR",
            f"hard-fail pattern matched: {hard_fail_matches[0]}",
            "log_pattern",
            evidence,
            "tool_error",
        )

    if return_code != 0:
        evidence.append(
            evidence_record("return_code", log_path, root, "FAIL", f"process exited {return_code}")
        )
        return _decision(
            policy_name,
            policy,
            extensions,
            "FAIL",
            f"process exited {return_code}",
            "return_code",
            evidence,
            "sim_failure",
        )

    for pattern in policy["required_patterns"]:
        if not re.search(pattern, text, flags=re.MULTILINE):
            message = f"required pattern missing: {pattern}"
            evidence.append(evidence_record("required_pattern", log_path, root, "FAIL", message))
            return _decision(
                policy_name,
                policy,
                extensions,
                "FAIL",
                message,
                "log_pattern",
                evidence,
                "sim_failure",
            )

    unignored_failures: list[str] = []
    for line in _match_lines(policy["fail_patterns"], text):
        if _is_ignored(line, policy["ignore_patterns"]):
            evidence.append(evidence_record("fail_pattern", log_path, root, "IGNORED", line))
        else:
            unignored_failures.append(line)
            evidence.append(evidence_record("fail_pattern", log_path, root, "FAIL", line))
    if unignored_failures:
        return _decision(
            policy_name,
            policy,
            extensions,
            "FAIL",
            f"fail pattern matched: {unignored_failures[0]}",
            "log_pattern",
            evidence,
            "sim_failure",
        )

    for pattern in policy["summary_patterns"]:
        matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
        if not matches:
            continue
        record = _summary_evidence(pattern, matches[-1], log_path, root)
        evidence.append(record)
        if record["status"] == "FAIL":
            return _decision(
                policy_name,
                policy,
                extensions,
                "FAIL",
                record["message"],
                "log_summary",
                evidence,
                "sim_failure",
            )
        positive = True

    for line in _match_lines(policy["pass_patterns"], text):
        evidence.append(evidence_record("pass_pattern", log_path, root, "PASS", line))
        if not policy["structured_results"]:
            positive = True

    if structured_unknown:
        return _decision(
            policy_name,
            policy,
            extensions,
            "UNKNOWN",
            "structured result missing or inconclusive",
            "structured_result",
            evidence,
            "unknown",
        )
    if policy["require_positive_evidence"] and not positive:
        return _decision(
            policy_name,
            policy,
            extensions,
            "UNKNOWN",
            "no positive pass evidence matched",
            "log_pattern",
            evidence,
            "unknown",
        )
    return _decision(
        policy_name,
        policy,
        extensions,
        "PASS",
        "positive pass evidence matched",
        "structured_result" if policy["structured_results"] else "log_pattern",
        evidence,
        None,
    )
