# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""TOML config loading and validation for the native DV runner."""

from __future__ import annotations

import ast
import copy
import os
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from .models import ConfigError, Dut, Flow, TestCatalog, TestEntry
from .paths import configs_root, repo_path, repo_rel

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _tomllib  # type: ignore[import-not-found,no-redef]
    except ModuleNotFoundError:
        _tomllib = None  # type: ignore[assignment]


CANONICAL_STAGES = {
    "flist",
    "hdl_compile",
    "c_compile",
    "elaborate",
    "sim",
    "regress",
    "cov_merge",
    "cov_report",
    "formal",
    "clean",
}

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

IMPLEMENTED_STAGE_KINDS = {
    "noop",
    "clean",
    # Generic kinds dispatched per (tool, framework) at run time: `filelist` resolves to the
    # Bender filelist generator, `hdl_compile` to the framework's build adapter (cocotb model
    # build, or the folded VCS analyze+elaborate for SV-UVM), `sim` to the framework's launcher.
    "filelist",
    "hdl_compile",
    "sim",
    "bender_filelist",
    "verilator_filelist",
    "verilator_compile",
    "c_compile",
    "cocotb_build",
    "cocotb_sim",
    "cocotb_verilator",
    "coverage_merge",
    "coverage_report",
    "formal_run",
    "vcs_filelist",
    "vcs_analyze",
    "vcs_compile",
    "vcs_elaborate",
    "vcs_sim",
    "xrun_filelist",
    "xrun_analyze",
    "xrun_compile",
    "xrun_elaborate",
    "xrun_sim",
}

STAGE_KIND_COMPATIBILITY = {
    "flist": {
        "filelist",
        "bender_filelist",
        "verilator_filelist",
        "vcs_filelist",
        "xrun_filelist",
        "noop",
    },
    "hdl_compile": {
        "hdl_compile",
        "cocotb_build",
        "verilator_compile",
        "vcs_analyze",
        "vcs_compile",
        "xrun_analyze",
        "xrun_compile",
        "noop",
    },
    "c_compile": {"c_compile", "noop"},
    "elaborate": {"vcs_elaborate", "xrun_elaborate", "cocotb_build", "noop"},
    "sim": {"sim", "cocotb_sim", "cocotb_verilator", "vcs_sim", "xrun_sim", "noop"},
    "regress": {"sim", "cocotb_sim", "cocotb_verilator", "vcs_sim", "xrun_sim", "noop"},
    "cov_merge": {"coverage_merge", "noop"},
    "cov_report": {"coverage_report", "noop"},
    "formal": {"formal_run", "noop"},
    "clean": {"clean", "noop"},
}

COMMON_PLACEHOLDERS = {
    "flow",
    "kind",
    "framework",
    "tool",
    "executor",
    "target",
    "item",
    "seed",
    "jobs",
    "sim_jobs",
    "run_dir",
    "repo_root",
    "waves",
}
ALL_PLACEHOLDERS = COMMON_PLACEHOLDERS | {
    "fw_target",
    "build_dir",
    "build_cov_dir",
    "cov_dir",
    "design_db",
    "merged",
    "report",
    "inputs",
    "queue",
    "cores",
    "mem_mb",
    "walltime",
    "joblog",
    "jobname",
    "image",
}

# Placeholders of a formal launch template: the `argv` array on a `kind = "formal"` tool table
# in simulators.toml, or the `argv` override on an `[formal.apps.<app>.<tool>]` table. Scalar
# placeholders render inside any element.
FORMAL_SCALAR_PLACEHOLDERS = {"binary", "script", "cwd", "run_dir", "item"}
# A list placeholder is an element on its own and splices zero or more argv tokens.
FORMAL_LIST_PLACEHOLDERS = {"args", "formal_args"}
# An optional placeholder has a value only when the CLI supplies one; it sits inside an optional
# group (a nested array), which renders whole or not at all.
FORMAL_OPTIONAL_PLACEHOLDERS = {"proof_depth"}
FORMAL_PLACEHOLDERS = (
    FORMAL_SCALAR_PLACEHOLDERS | FORMAL_LIST_PLACEHOLDERS | FORMAL_OPTIONAL_PLACEHOLDERS
)
FormalArgvTemplate = list[str | list[str]]

# `[formal.apps.<app>.<tool>.evidence]`: the summary file a backend without a native task
# summary writes, and the line patterns that grade it. `summary` renders these placeholders and
# resolves against the app's `cwd` when relative.
FORMAL_EVIDENCE_KEYS = {
    "summary",
    "pass_patterns",
    "fail_patterns",
    "inconclusive_patterns",
    "cover_patterns",
    "unreached_patterns",
}
FORMAL_EVIDENCE_REQUIRED_PATTERNS = ("pass_patterns", "fail_patterns")
FORMAL_EVIDENCE_PLACEHOLDERS = {"run_dir", "item", "cwd"}

# Tool-table keys that describe one deployment rather than the tool: a site file
# (runlib.site) supplies them and the checked-in registry rejects them.
SITE_ONLY_TOOL_KEYS = {"launcher", "extra_env", "setup_hook"}

# Executor registry (executors.toml). Schema 1 declares `[local]` and a cluster table named
# by one `binary`; schema 2 names a `driver` and every scheduler command the driver runs, so
# `--doctor` can check each command and a site can retarget any of them in configuration.
EXECUTOR_SCHEMA_VERSIONS = {1, 2}
EXECUTOR_KINDS = {"local", "cluster"}
# Driver names a cluster table may select; `runlib.executors` says which of them dispatch.
CLUSTER_DRIVERS = frozenset({"lsf", "slurm"})
LOCAL_EXECUTOR_KEYS = {"kind", "description", "submit_argv", "wait_mode"}
CLUSTER_EXECUTOR_V1_KEYS = {
    "kind",
    "binary",
    "submit_argv",
    "wait_mode",
    "env_passthrough",
    "defaults",
}
CLUSTER_EXECUTOR_KEYS = {
    "kind",
    "description",
    "driver",
    "binaries",
    "wait_mode",
    "submit_argv",
    "query_argv",
    "history_argv",
    "cancel_argv",
    "worker_argv",
    "history_parser",
    "env_passthrough",
    "defaults",
    "limits",
    "setup_hook",
    "arrays",
    "builds",
    "build_defaults",
    "build_submit_argv",
}
# Where a cluster executor runs the target builds.
EXECUTOR_BUILD_MODES = {"local", "scheduler"}
# Executor keys that describe one deployment; the checked-in registry rejects them.
SITE_ONLY_EXECUTOR_KEYS = {"setup_hook"}
# The normalized resource vocabulary: an executor's `defaults`, a stage's `resources`, and the
# `--queue/--cores/--mem-mb/--walltime` flags all speak it.
EXECUTOR_RESOURCE_KEYS = {"queue", "cores", "mem_mb", "walltime"}
# `[<executor>.limits]`: the coordinator loop's knobs, each with the bound a value must meet.
EXECUTOR_LIMIT_KEYS: dict[str, tuple[type, float]] = {
    "max_in_flight": (int, 1),
    "submit_batch_size": (int, 1),
    "query_batch_size": (int, 1),
    "poll_interval_sec": (float, 0.1),
    "artifact_grace_sec": (float, 0),
    "cancel_grace_sec": (float, 0),
    "command_timeout_sec": (float, 1),
    "array_chunk_size": (int, 1),
}
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Placeholders an executor argv template may render. Resource values come in every unit a
# scheduler asks for, so a site template picks `{mem_gb}` or `{walltime_min}` as needed.
EXECUTOR_RESOURCE_PLACEHOLDERS = {
    "queue",
    "cores",
    "mem_mb",
    "mem_gb",
    "walltime",
    "walltime_sec",
    "walltime_min",
    "walltime_hms",
}
EXECUTOR_SUBMIT_PLACEHOLDERS = EXECUTOR_RESOURCE_PLACEHOLDERS | {
    "joblog",
    "jobname",
    "array_range",
    "image",
    "script",
    "manifest",
    "python",
    "run_dir",
    "repo_root",
    "leaf_dir",
    "task_id",
    "executor",
}
# `{job_ids_argv}` splices one token per job id; the other two render inside one token.
EXECUTOR_QUERY_PLACEHOLDERS = {"job_id", "job_ids_csv", "job_ids_argv"}
EXECUTOR_WORKER_PLACEHOLDERS = {"python", "manifest", "repo_root", "run_dir", "leaf_dir", "task_id"}
EXECUTOR_TEMPLATE_PLACEHOLDERS = {
    "submit_argv": EXECUTOR_SUBMIT_PLACEHOLDERS,
    "build_submit_argv": EXECUTOR_SUBMIT_PLACEHOLDERS,
    "query_argv": EXECUTOR_QUERY_PLACEHOLDERS,
    "history_argv": EXECUTOR_QUERY_PLACEHOLDERS,
    "cancel_argv": EXECUTOR_QUERY_PLACEHOLDERS,
    "worker_argv": EXECUTOR_WORKER_PLACEHOLDERS,
}
# A wall-time request: minutes (`90`), a unit suffix (`90m`, `2h`, `30s`, `1d`), `HH:MM`,
# `HH:MM:SS`, or `D-HH[:MM[:SS]]`. Two colon-separated fields are hours and minutes.
WALLTIME_UNIT_RE = re.compile(r"^(\d+)([smhd])$")
WALLTIME_CLOCK_RE = re.compile(r"^(?:(\d+)-)?(\d+)(?::(\d{1,2}))?(?::(\d{1,2}))?$")
_WALLTIME_UNIT_SEC = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_walltime_sec(text: str) -> int:
    """Seconds in a wall-time request; a ConfigError names the accepted forms."""
    value = str(text).strip()
    total = 0
    if value.isdigit():
        total = int(value) * 60
    elif unit := WALLTIME_UNIT_RE.match(value):
        total = int(unit.group(1)) * _WALLTIME_UNIT_SEC[unit.group(2)]
    elif clock := WALLTIME_CLOCK_RE.match(value):
        days, hours, minutes, seconds = clock.groups()
        if int(minutes or 0) < 60 and int(seconds or 0) < 60:
            total = int(hours) * 3600 + int(minutes or 0) * 60 + int(seconds or 0)
            if days:
                total += int(days) * 86400
    if total > 0:
        return total
    raise ConfigError(
        f"invalid walltime {text!r}: use minutes, a unit suffix (s/m/h/d), HH:MM, HH:MM:SS, "
        "or D-HH:MM:SS"
    )


def validate_resource_table(table: Any, where: str) -> dict[str, Any]:
    """Shape-check a normalized resource table and return it with typed values."""
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    validate_allowed_keys(table, EXECUTOR_RESOURCE_KEYS, where)
    out: dict[str, Any] = {}
    if "queue" in table:
        if not isinstance(table["queue"], str) or not table["queue"]:
            raise ConfigError(f"{where}.queue must be a non-empty string")
        out["queue"] = table["queue"]
    for key in ("cores", "mem_mb"):
        if key in table:
            value = table[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"{where}.{key} must be a positive integer")
            out[key] = value
    if "walltime" in table:
        value = table["walltime"]
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where}.walltime must be a non-empty string")
        try:
            parse_walltime_sec(value)
        except ConfigError as exc:
            raise ConfigError(f"{where}.walltime: {exc}") from exc
        out["walltime"] = value
    return out


def validate_limits_table(table: Any, where: str) -> dict[str, Any]:
    if not isinstance(table, dict):
        raise ConfigError(f"{where} must be a table")
    validate_allowed_keys(table, set(EXECUTOR_LIMIT_KEYS), where)
    out: dict[str, Any] = {}
    for key, value in table.items():
        kind, floor = EXECUTOR_LIMIT_KEYS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{where}.{key} must be a number")
        if kind is int and not isinstance(value, int):
            raise ConfigError(f"{where}.{key} must be an integer")
        if value < floor:
            raise ConfigError(f"{where}.{key} must be at least {floor:g}")
        out[key] = value
    return out


def validate_argv_template(template: Any, where: str, allowed: set[str], *, required: bool) -> None:
    """An executor argv template: strings and optional groups over the allowed placeholders."""
    if template is None:
        if required:
            raise ConfigError(f"{where} is required")
        return
    if not isinstance(template, list) or (required and not template):
        raise ConfigError(f"{where} must be a non-empty list of argv tokens")
    for idx, element in enumerate(template):
        if isinstance(element, list):
            if not element or not all(isinstance(token, str) and token for token in element):
                raise ConfigError(f"{where}[{idx}]: an optional group holds non-empty strings only")
            continue
        if not isinstance(element, str) or not element:
            raise ConfigError(f"{where}[{idx}] must be a non-empty string or a group")
    validate_placeholders_in_value(template, where, allowed)


TOOL_KINDS = {"simulation", "formal"}
# A tool table's `min_version`: a dotted release number, compared by the doctor against the
# first such number in the release line the tool's binary prints.
MIN_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

TOP_LEVEL_KEYS = {
    "schema_version",
    "name",
    "profile",
    "kind",
    "framework",
    "visibility",
    "runnability",
    "license",
    "default_tool",
    "tools",
    "description",
    "scheduler",
    "defaults",
    "target_defaults",
    "native",
    "testlist",
    "build",
    "cocotb",
    "c_build",
    "run_modes",
    "targets",
    "coverage",
    "pass_fail",
    "sim",
    "formal",
    "dut",
    "tb",
    # Injected by load_dut when --overlay/OCAH_DV_OVERLAY is active; a sim config or profile
    # may never set them (overlays are explicit-activation only — see apply_adopter_overlay).
    "adopter_overlay",
    "adopter_overlay_env",
}

BUILD_KEYS = {
    "top_module",
    "top_file",
    "filelist",
    "bender_filelist",
    "work_dir",
    "common_bender_targets",
    "bender_targets",
    "incdirs",
    "stubs",
    "sources",
    "source_lists",
    "exclude_files",
    "options",
    "verilator",
    "xcelium",
    "vcs",
}

# Keys a `[build].source_lists` fragment file may carry (see _expand_source_lists).
SOURCE_LIST_KEYS = {"description", "incdirs", "sources"}

# Keys an adopter overlay file (--overlay / OCAH_DV_OVERLAY) may carry (see
# apply_adopter_overlay). The layer is append-only: every allowed key ADDS to the
# merged DUT view (build inputs, target defines/flags, run args, process environment) and
# none can replace or remove what the checked-in configs declare — so a run with an overlay
# differs from the baseline only by the overlay's own additions.
ADOPTER_OVERLAY_KEYS = {
    "description",
    "frameworks",
    "build",
    "sim",
    "env",
    "target_defaults",
    "targets",
}
ADOPTER_OVERLAY_BUILD_KEYS = {"incdirs", "sources", "source_lists"}
ADOPTER_OVERLAY_SIM_KEYS = {"args"}
ADOPTER_OVERLAY_TARGET_KEYS = {"defines", "flags", "tools"}

BUILD_OPTIONS_KEYS = {
    "build_jobs",
    "cflags",
    "cache_enabled",
    "rebuild",
    "cache_key_extra",
}

COCOTB_KEYS = {
    "python_root",
    "test_dir",
    "python_paths",
    "results_dir",
    "cocotb_log",
}

FRAMEWORK_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Keys a `[frameworks.<fw>]` section may overlay onto the merged config when that framework is
# selected. Any other key in the section is the framework's own runtime config (e.g. the cocotb
# path keys), projected into the merged config under the framework's name.
FRAMEWORK_OVERLAY_KEYS = {
    "description",
    "default_tool",
    "tools",
    "visibility",
    "runnability",
    "license",
    "defaults",
    "target_defaults",
    "native",
    "testlist",
    "build",
    "c_build",
    "run_modes",
    "targets",
    "coverage",
    "pass_fail",
    "sim",
    "formal",
    "scheduler",
}

# Per-framework runtime keys allowed directly in that framework's section.
FRAMEWORK_RUNTIME_KEYS: dict[str, set[str]] = {"cocotb": COCOTB_KEYS}

TARGET_KEYS = {
    "description",
    "build_dir",
    "work_dir",
    "filelist",
    "bender_filelist",
    "bender_targets",
    "defines",
    "flags",
    "sources",
    "stubs",
    "exclude_files",
    "tools",
}

TARGET_TOOL_KEYS = {"flags"}
RUN_MODE_KEYS = {"description", "timeout_sec", "args", "plusargs"}
TESTLIST_KEYS = {"schema_version", "includes", "tests", "groups"}
TEST_KEYS = {
    "name",
    "module",
    "target",
    "seed",
    "reseed",
    "timeout_sec",
    "tags",
    "run_modes",
    "tools",
    "firmware",
    "expect_fail",
    "expect_fail_match",
    "args",
    "overrides",
}

# Runtime knobs a `[tests.overrides.<fw>]` subtable may set for one framework.
TEST_OVERRIDE_KEYS = {"seed", "timeout_sec", "args"}
GROUP_KEYS = {"name", "tests", "expected_count"}

COVERAGE_TOOL_KEYS = {
    "artifact",
    "backend",
    "build_args",
    "compile_args",
    "design_artifact",
    "design_db",
    "exclude_files",
    "fail_under",
    "input_glob",
    "merge_cmd",
    "combine_cmd",
    "merged_name",
    "parser",
    "policy_file",
    "report_cmd",
    "sim_args",
    "test_args",
}
COVERAGE_LIST_KEYS = {
    "build_args",
    "compile_args",
    "exclude_files",
    "merge_cmd",
    "combine_cmd",
    "report_cmd",
    "sim_args",
    "test_args",
}
COVERAGE_PARSERS = {"verilator", "urg", "imc"}


def _strip_toml_comment(line: str) -> str:
    in_string = ""
    escaped = False
    for idx, char in enumerate(line):
        if in_string:
            if in_string == '"' and escaped:
                escaped = False
                continue
            if in_string == '"' and char == "\\":
                escaped = True
                continue
            if char == in_string:
                in_string = ""
            continue
        if char in {'"', "'"}:
            in_string = char
        elif char == "#":
            return line[:idx]
    return line


def _toml_value_complete(value: str) -> bool:
    depth = 0
    in_string = ""
    escaped = False
    for char in value:
        if in_string:
            if in_string == '"' and escaped:
                escaped = False
                continue
            if in_string == '"' and char == "\\":
                escaped = True
                continue
            if char == in_string:
                in_string = ""
            continue
        if char in {'"', "'"}:
            in_string = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth == 0 and not in_string


def _split_toml_array(inner: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    in_string = ""
    escaped = False
    for idx, char in enumerate(inner):
        if in_string:
            if in_string == '"' and escaped:
                escaped = False
                continue
            if in_string == '"' and char == "\\":
                escaped = True
                continue
            if char == in_string:
                in_string = ""
            continue
        if char in {'"', "'"}:
            in_string = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            item = inner[start:idx].strip()
            if item:
                items.append(item)
            start = idx + 1
    item = inner[start:].strip()
    if item:
        items.append(item)
    return items


def _parse_toml_value(value: str, path: Path, line_no: int) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_toml_value(item, path, line_no) for item in _split_toml_array(inner)]
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ConfigError(f"{path}:{line_no}: invalid TOML string") from exc
    if re.fullmatch(r"[-+]?(0|[1-9][0-9_]*|0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+)", value):
        return int(value.replace("_", ""), 0)
    if re.fullmatch(r"[-+]?(?:[0-9][0-9_]*)?\.[0-9][0-9_]*", value):
        return float(value.replace("_", ""))
    raise ConfigError(f"{path}:{line_no}: unsupported TOML value `{value}`")


def _ensure_toml_table(
    data: dict[str, Any], parts: list[str], path: Path, line_no: int
) -> dict[str, Any]:
    table = data
    for part in parts:
        next_table = table.setdefault(part, {})
        if not isinstance(next_table, dict):
            raise ConfigError(f"{path}:{line_no}: `{'.'.join(parts)}` conflicts with a scalar")
        table = next_table
    return table


def _assign_toml_value(
    table: dict[str, Any], key: str, value: Any, path: Path, line_no: int
) -> None:
    parts = [part.strip() for part in key.split(".")]
    if not all(parts):
        raise ConfigError(f"{path}:{line_no}: invalid TOML key `{key}`")
    target = _ensure_toml_table(table, parts[:-1], path, line_no)
    if parts[-1] in target:
        raise ConfigError(f"{path}:{line_no}: duplicate TOML key `{key}`")
    target[parts[-1]] = value


def _load_toml_subset(path: Path) -> dict[str, Any]:
    """Small TOML reader for the repo's DV configs when Python lacks tomllib/tomli.

    It covers only the constructs used by these configs: tables, arrays of tables,
    strings, booleans, integers, floats, and arrays.
    """
    data: dict[str, Any] = {}
    current = data
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = 0
    while idx < len(lines):
        idx += 1
        line_no = idx
        line = _strip_toml_comment(lines[idx - 1]).strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            parts = [part.strip() for part in line[2:-2].strip().split(".")]
            if not all(parts):
                raise ConfigError(f"{path}:{line_no}: invalid TOML array table `{line}`")
            parent = _ensure_toml_table(data, parts[:-1], path, line_no)
            entries = parent.setdefault(parts[-1], [])
            if not isinstance(entries, list):
                raise ConfigError(f"{path}:{line_no}: `{'.'.join(parts)}` conflicts with a scalar")
            current = {}
            entries.append(current)
            continue
        if line.startswith("[") and line.endswith("]"):
            parts = [part.strip() for part in line[1:-1].strip().split(".")]
            if not all(parts):
                raise ConfigError(f"{path}:{line_no}: invalid TOML table `{line}`")
            current = _ensure_toml_table(data, parts, path, line_no)
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{line_no}: expected TOML key/value")

        key, value = line.split("=", 1)
        value = value.strip()
        while not _toml_value_complete(value):
            idx += 1
            if idx > len(lines):
                raise ConfigError(f"{path}:{line_no}: unterminated TOML value")
            value += " " + _strip_toml_comment(lines[idx - 1]).strip()
        _assign_toml_value(
            current, key.strip(), _parse_toml_value(value, path, line_no), path, line_no
        )
    return data


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing TOML file: {path}")
    if _tomllib is not None:
        with path.open("rb") as handle:
            return _tomllib.load(handle)
    return _load_toml_subset(path)


def as_str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"`{key}` must be a list of strings")
    return list(value)


def as_int(value: Any, key: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"`{key}` must be an integer") from exc


def validate_allowed_keys(section: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unsupported key(s): {', '.join(unknown)}")


def validate_placeholders_in_value(
    value: Any, where: str, allowed: set[str] = ALL_PLACEHOLDERS
) -> None:
    if isinstance(value, str):
        unknown = sorted({name for name in PLACEHOLDER_RE.findall(value) if name not in allowed})
        if unknown:
            raise ConfigError(
                f"{where}: unsupported placeholder(s): {', '.join('{' + name + '}' for name in unknown)}"
            )
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            validate_placeholders_in_value(item, f"{where}[{idx}]", allowed)
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_placeholders_in_value(item, f"{where}.{key}", allowed)


def _validate_formal_argv_element(text: str, where: str, *, in_group: bool) -> None:
    names = PLACEHOLDER_RE.findall(text)
    unknown = sorted(set(names) - FORMAL_PLACEHOLDERS)
    if unknown:
        raise ConfigError(
            f"{where}: unsupported placeholder(s): {', '.join('{' + name + '}' for name in unknown)}"
        )
    for name in names:
        if name in FORMAL_LIST_PLACEHOLDERS:
            if in_group:
                raise ConfigError(
                    f"{where}: list placeholder {{{name}}} cannot sit inside an optional group"
                )
            if text != "{" + name + "}":
                raise ConfigError(
                    f"{where}: list placeholder {{{name}}} must be an element on its own"
                )
        elif name in FORMAL_OPTIONAL_PLACEHOLDERS and not in_group:
            raise ConfigError(
                f"{where}: optional placeholder {{{name}}} must sit inside an optional group, "
                f'for example ["-depth", "{{{name}}}"]'
            )


def validate_formal_argv_template(value: Any, where: str) -> FormalArgvTemplate:
    """Check a formal launch template and return it.

    A template is a non-empty array whose elements are strings or optional groups (nested arrays
    of strings). Every placeholder is one of FORMAL_PLACEHOLDERS; a list placeholder is an
    element on its own outside any group; an optional placeholder appears only inside a group,
    and every group references one.
    """
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: `argv` must be a non-empty list")
    template: FormalArgvTemplate = []
    for idx, element in enumerate(value):
        label = f"{where}[{idx}]"
        if isinstance(element, str):
            _validate_formal_argv_element(element, label, in_group=False)
            template.append(element)
        elif isinstance(element, list):
            if not element or not all(isinstance(sub, str) for sub in element):
                raise ConfigError(f"{label}: an optional group must be a non-empty list of strings")
            for sub_idx, sub in enumerate(element):
                _validate_formal_argv_element(sub, f"{label}[{sub_idx}]", in_group=True)
            if not FORMAL_OPTIONAL_PLACEHOLDERS & _template_placeholders([element]):
                raise ConfigError(
                    f"{label}: an optional group must reference an optional placeholder "
                    f"({', '.join('{' + n + '}' for n in sorted(FORMAL_OPTIONAL_PLACEHOLDERS))})"
                )
            template.append(list(element))
        else:
            raise ConfigError(f"{label}: `argv` elements are strings or optional groups")
    return template


def _template_placeholders(template: FormalArgvTemplate) -> set[str]:
    names: set[str] = set()
    for element in template:
        for text in element if isinstance(element, list) else [element]:
            names.update(PLACEHOLDER_RE.findall(text))
    return names


def formal_template_placeholders(template: FormalArgvTemplate) -> set[str]:
    """Every placeholder a validated template references."""
    return _template_placeholders(template)


def render_formal_argv(
    template: FormalArgvTemplate,
    scalars: dict[str, str],
    lists: dict[str, list[str]],
    optional: dict[str, str | None],
) -> list[str]:
    """Render a validated formal launch template into argv.

    A list placeholder element splices its tokens; an optional group renders when every optional
    placeholder it references has a value and is dropped otherwise.
    """
    values = dict(scalars)
    values.update({name: value for name, value in optional.items() if value is not None})

    def render(text: str) -> str:
        rendered = text
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", value)
        return rendered

    argv: list[str] = []
    for element in template:
        if isinstance(element, list):
            needed = _template_placeholders([element]) & set(optional)
            if any(optional[name] is None for name in needed):
                continue
            argv.extend(render(sub) for sub in element)
            continue
        names = PLACEHOLDER_RE.findall(element)
        if len(names) == 1 and names[0] in lists and element == "{" + names[0] + "}":
            argv.extend(lists[names[0]])
            continue
        argv.append(render(element))
    return argv


def validate_formal_evidence_hook(table: Any, where: str) -> dict[str, Any]:
    """Check an app's `evidence` table and return it."""
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: `evidence` must be a table")
    validate_allowed_keys(table, FORMAL_EVIDENCE_KEYS, where)
    summary = table.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ConfigError(f"{where}: `summary` must name the summary file")
    unknown = sorted(set(PLACEHOLDER_RE.findall(summary)) - FORMAL_EVIDENCE_PLACEHOLDERS)
    if unknown:
        allowed = ", ".join("{" + name + "}" for name in sorted(FORMAL_EVIDENCE_PLACEHOLDERS))
        raise ConfigError(
            f"{where}.summary: unknown placeholder(s) {', '.join('{' + n + '}' for n in unknown)}"
            f"; allowed: {allowed}"
        )
    for key in sorted(FORMAL_EVIDENCE_KEYS - {"summary"}):
        patterns = as_str_list(table.get(key), f"{where}.{key}")
        if key in FORMAL_EVIDENCE_REQUIRED_PATTERNS and not patterns:
            raise ConfigError(f"{where}: `{key}` must list at least one pattern")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"{where}.{key}: invalid regex `{pattern}`: {exc}") from exc
    return table


def validate_formal_apps(formal: Any, where: str) -> None:
    """Check every `argv` override and `evidence` table under `[formal.apps.<app>.<tool>]`."""
    if not isinstance(formal, dict):
        return
    apps = formal.get("apps", {})
    if not isinstance(apps, dict):
        return
    for app_name, app in apps.items():
        if not isinstance(app, dict):
            continue
        for tool, tool_cfg in app.items():
            if not isinstance(tool_cfg, dict):
                continue
            table_where = f"{where} [formal.apps.{app_name}.{tool}]"
            if "argv" in tool_cfg:
                validate_formal_argv_template(tool_cfg["argv"], f"{table_where}.argv")
            if "evidence" in tool_cfg:
                validate_formal_evidence_hook(tool_cfg["evidence"], f"{table_where}.evidence")


def validate_coverage_tool_table(
    table: dict[str, Any],
    where: str,
    *,
    require_complete: bool = False,
) -> None:
    """Validate one config-driven coverage backend table."""

    validate_allowed_keys(table, COVERAGE_TOOL_KEYS, where)
    for key in COVERAGE_LIST_KEYS:
        if key in table:
            as_str_list(table.get(key), f"{where}.{key}")
    for key in (
        "artifact",
        "backend",
        "design_artifact",
        "design_db",
        "input_glob",
        "merged_name",
        "parser",
        "policy_file",
    ):
        if key in table and (
            not isinstance(table.get(key), str) or not str(table.get(key)).strip()
        ):
            raise ConfigError(f"{where}.{key} must be a non-empty string")
    if "parser" in table and table.get("parser") not in COVERAGE_PARSERS:
        raise ConfigError(f"{where}.parser must be one of: {', '.join(sorted(COVERAGE_PARSERS))}")
    if "fail_under" in table:
        try:
            threshold = float(table["fail_under"])
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{where}.fail_under must be a number") from exc
        if threshold < 0.0 or threshold > 100.0:
            raise ConfigError(f"{where}.fail_under must be between 0 and 100")
    if require_complete:
        missing = [
            key
            for key in (
                "artifact",
                "backend",
                "input_glob",
                "merged_name",
                "merge_cmd",
                "report_cmd",
                "parser",
            )
            if key not in table
        ]
        if missing:
            raise ConfigError(f"{where} missing required coverage key(s): {', '.join(missing)}")
    validate_placeholders_in_value(table, where)


def validate_stage_table(stage_name: str, stage: dict[str, Any], where: str) -> None:
    kind = stage.get("kind")
    if not isinstance(kind, str):
        raise ConfigError(f"{where}: native stage `{stage_name}` missing string `kind`")
    if kind not in IMPLEMENTED_STAGE_KINDS:
        raise ConfigError(f"{where}: unsupported native stage kind `{kind}`")
    compatible = STAGE_KIND_COMPATIBILITY.get(stage_name, set())
    if kind not in compatible:
        raise ConfigError(f"{where}: stage `{stage_name}` cannot use kind `{kind}`")

    allowed = {
        "kind",
        "note",
        "paths",
        "verilator",
        "xcelium",
        "vcs",
        "default_executor",
        "resources",
    }
    validate_allowed_keys(stage, allowed, f"{where} [native.stages.{stage_name}]")
    if "default_executor" in stage and (
        not isinstance(stage["default_executor"], str) or not stage["default_executor"]
    ):
        raise ConfigError(
            f"{where} [native.stages.{stage_name}].default_executor must be a non-empty string"
        )
    if "resources" in stage:
        validate_resource_table(
            stage["resources"], f"{where} [native.stages.{stage_name}].resources"
        )
    validate_placeholders_in_value(stage, f"{where} [native.stages.{stage_name}]")


def validate_testlist_pointer(flow: Dut, root: Path) -> None:
    testlist = flow.raw.get("testlist", {})
    if not isinstance(testlist, dict):
        raise ConfigError(f"{flow.path}: [testlist] must be a table")
    validate_allowed_keys(testlist, {"path", "format"}, f"{flow.path} [testlist]")
    if str(testlist.get("format", "toml_list")) != "toml_list":
        raise ConfigError(f"{flow.path}: [testlist].format must be `toml_list`")
    path_text = testlist.get("path")
    if path_text is None:
        return
    if not isinstance(path_text, str) or not path_text:
        raise ConfigError(f"{flow.path}: [testlist].path must be a non-empty string")
    raw_path = Path(path_text).expanduser()
    if raw_path.is_absolute():
        raise ConfigError(f"{flow.path}: [testlist].path must be relative to the DUT DV root")
    resolved = (flow.path.parent / raw_path).resolve()
    dut_root = flow.path.parent.resolve()
    try:
        resolved.relative_to(dut_root)
    except ValueError as exc:
        raise ConfigError(f"{flow.path}: [testlist].path resolves outside the DUT DV root") from exc
    if not resolved.is_file():
        raise ConfigError(f"{flow.path}: missing testlist: {resolved}")


def validate_native_config_shape(flow: Dut, root: Path) -> None:
    data = flow.raw
    validate_allowed_keys(data, TOP_LEVEL_KEYS, str(flow.path))

    scheduler = data.get("scheduler", {})
    if isinstance(scheduler, dict):
        validate_allowed_keys(
            scheduler, {"default_executor", "allowed"}, f"{flow.path} [scheduler]"
        )

    native = data.get("native", {})
    if native:
        if not isinstance(native, dict):
            raise ConfigError(f"{flow.path}: [native] must be a table")
        validate_allowed_keys(native, {"enabled", "status", "stages"}, f"{flow.path} [native]")

    stages = flow_stages(flow)
    for stage_name, stage in stages.items():
        if stage_name not in CANONICAL_STAGES:
            raise ConfigError(f"{flow.path}: unsupported native stage `{stage_name}`")
        if not isinstance(stage, dict):
            raise ConfigError(f"{flow.path}: [native.stages.{stage_name}] must be a table")
        validate_stage_table(stage_name, stage, str(flow.path))

    validate_testlist_pointer(flow, root)

    build = data.get("build", {})
    if isinstance(build, dict):
        if "manifest" in build:
            raise ConfigError(
                f"{flow.path}: [build].manifest is external-only; native flow must not reference .core"
            )
        validate_allowed_keys(build, BUILD_KEYS, f"{flow.path} [build]")
        options = build.get("options", {})
        if isinstance(options, dict):
            validate_allowed_keys(options, BUILD_OPTIONS_KEYS, f"{flow.path} [build.options]")
        for tool in ("verilator", "xcelium", "vcs"):
            tool_cfg = build.get(tool, {})
            if isinstance(tool_cfg, dict):
                validate_placeholders_in_value(tool_cfg, f"{flow.path} [build.{tool}]")
        validate_placeholders_in_value(build, f"{flow.path} [build]")

    cocotb = data.get("cocotb", {})
    if isinstance(cocotb, dict):
        validate_allowed_keys(cocotb, COCOTB_KEYS, f"{flow.path} [cocotb]")
        validate_placeholders_in_value(cocotb, f"{flow.path} [cocotb]")

    run_modes = data.get("run_modes", {})
    if isinstance(run_modes, dict):
        for name, run_mode in run_modes.items():
            if not isinstance(run_mode, dict):
                raise ConfigError(f"{flow.path}: [run_modes.{name}] must be a table")
            validate_allowed_keys(run_mode, RUN_MODE_KEYS, f"{flow.path} [run_modes.{name}]")
            validate_placeholders_in_value(run_mode, f"{flow.path} [run_modes.{name}]")

    for section_name in ("target_defaults", "targets"):
        targets = data.get(section_name, {})
        if isinstance(targets, dict):
            for name, target in targets.items():
                if not isinstance(target, dict):
                    raise ConfigError(f"{flow.path}: [{section_name}.{name}] must be a table")
                validate_allowed_keys(target, TARGET_KEYS, f"{flow.path} [{section_name}.{name}]")
                validate_placeholders_in_value(target, f"{flow.path} [{section_name}.{name}]")
                tools = target.get("tools", {})
                if isinstance(tools, dict):
                    for tool, tool_cfg in tools.items():
                        if not isinstance(tool_cfg, dict):
                            raise ConfigError(
                                f"{flow.path}: [{section_name}.{name}.tools.{tool}] must be a table"
                            )
                        validate_allowed_keys(
                            tool_cfg,
                            TARGET_TOOL_KEYS,
                            f"{flow.path} [{section_name}.{name}.tools.{tool}]",
                        )

    for section_name in ("coverage", "c_build", "formal", "sim"):
        section = data.get(section_name, {})
        if isinstance(section, dict):
            allowed = ALL_PLACEHOLDERS
            if section_name == "formal":
                allowed = ALL_PLACEHOLDERS | FORMAL_PLACEHOLDERS
            validate_placeholders_in_value(section, f"{flow.path} [{section_name}]", allowed)
    validate_formal_apps(data.get("formal"), str(flow.path))
    coverage = data.get("coverage", {})
    if isinstance(coverage, dict):
        for tool, table in coverage.items():
            if not isinstance(table, dict):
                raise ConfigError(f"{flow.path}: [coverage.{tool}] must be a table")
            validate_coverage_tool_table(
                table,
                f"{flow.path} [coverage.{tool}]",
            )


def config_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"`{key}` must be a table")
    return value


def config_list(data: dict[str, Any], key: str) -> list[str]:
    return as_str_list(data.get(key), key)


def sim_global_args(sim_cfg: dict[str, Any]) -> list[str]:
    """DUT-global run-stage args from ``[sim].args`` (the lowest-precedence run-arg layer).

    Run args append across layers with no dedup/override:
    ``[sim].args`` (profile + DUT, joined) < ``[run_modes.<name>].args`` < ``[[tests]].args`` < CLI.
    """
    return as_str_list(config_section(sim_cfg, "sim").get("args"), "sim.args")


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` onto `base`: tables merge per-key, everything else overlay wins."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def framework_sections(data: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    """The validated ``[frameworks.<name>]`` sections of a profile or DUT sim config.

    A profile supports the frameworks it declares this way; a DUT implements exactly the
    frameworks it declares this way. Section content splits into overlay tables
    (:data:`FRAMEWORK_OVERLAY_KEYS`) and the framework's own runtime keys
    (:data:`FRAMEWORK_RUNTIME_KEYS`).
    """
    sections = data.get("frameworks")
    if sections in (None, {}):
        return {}
    if not isinstance(sections, dict):
        raise ConfigError(f"{where}: [frameworks] must hold [frameworks.<name>] tables")
    out: dict[str, dict[str, Any]] = {}
    for fw, section in sections.items():
        if not isinstance(fw, str) or not FRAMEWORK_NAME_RE.match(fw):
            raise ConfigError(f"{where}: invalid framework name `{fw}`")
        if not isinstance(section, dict):
            raise ConfigError(f"{where}: [frameworks.{fw}] must be a table")
        runtime_allowed = FRAMEWORK_RUNTIME_KEYS.get(fw, set())
        unknown = sorted(set(section) - FRAMEWORK_OVERLAY_KEYS - runtime_allowed)
        if unknown:
            raise ConfigError(
                f"{where}: [frameworks.{fw}] unsupported key(s): {', '.join(unknown)}"
            )
        out[fw] = section
    return out


def _framework_split(section: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one ``[frameworks.<fw>]`` section into (overlay tables, runtime keys)."""
    overlay = {key: value for key, value in section.items() if key in FRAMEWORK_OVERLAY_KEYS}
    runtime = {key: value for key, value in section.items() if key not in FRAMEWORK_OVERLAY_KEYS}
    return overlay, runtime


def _merge_framework_config(
    profile_cfg: dict[str, Any],
    data: dict[str, Any],
    path: Path,
    profile_name: str,
    requested: str | None = None,
) -> tuple[dict[str, Any], str, list[str], str]:
    """Merge a frameworks-aware profile with a DUT sim config for the selected framework.

    ``requested`` is the CLI ``--framework`` value; selection order is CLI request >
    DUT ``default_framework`` > profile ``default_framework`` (when implemented) > the single
    implemented framework. Validation order: the profile supports the framework -> the DUT
    implements it (tool capability and bindings are checked later, downstream).

    Merge order (later wins): profile shared keys -> profile ``[frameworks.<selected>]`` ->
    DUT shared keys -> DUT ``[frameworks.<selected>]``. ``[sim].args`` append across all four
    layers. The selected section's runtime keys (e.g. the cocotb paths) are projected to the
    merged ``[<framework>]`` table, and the selection is recorded under ``framework``.

    Returns ``(merged, selected framework, implemented frameworks, default framework)``.
    """
    profile_where = f"profile `{profile_name}`"
    profile_sections = framework_sections(profile_cfg, profile_where)
    dut_sections = framework_sections(data, str(path))

    supported = list(profile_sections)
    implemented = list(dut_sections)
    unsupported = sorted(set(implemented) - set(supported))
    if unsupported:
        raise ConfigError(
            f"{path}: framework(s) not supported by profile `{profile_name}`: "
            f"{', '.join(unsupported)} (profile supports: {', '.join(supported)})"
        )
    if not implemented:
        raise ConfigError(
            f"{path}: a DUT implements a framework by declaring a [frameworks.<name>] table; "
            f"declare at least one (profile `{profile_name}` supports: {', '.join(supported)})"
        )
    for key, hint in (
        (
            "framework",
            "top-level `framework` is derived from the selected [frameworks.<fw>] section",
        ),
        ("cocotb", "[cocotb] moved to [frameworks.cocotb]"),
    ):
        if key in data:
            raise ConfigError(f"{path}: {hint}")

    dut_default = data.get("default_framework")
    profile_default = profile_cfg.get("default_framework")
    for value, where in ((dut_default, str(path)), (profile_default, profile_where)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ConfigError(f"{where}: `default_framework` must be a non-empty string")

    dut_name = str(data.get("name", path.stem))
    if dut_default and dut_default not in implemented:
        raise ConfigError(
            f"{path}: dut `{dut_name}` does not implement its `default_framework` "
            f"`{dut_default}` (implemented: {', '.join(implemented)})"
        )
    if dut_default:
        default_fw = str(dut_default)
    elif profile_default and profile_default in implemented:
        default_fw = str(profile_default)
    elif len(implemented) == 1:
        default_fw = implemented[0]
    else:
        default_fw = ""

    if requested:
        if requested not in supported:
            raise ConfigError(
                f"profile `{profile_name}` does not support framework `{requested}` "
                f"(supported: {', '.join(supported)})"
            )
        if requested not in implemented:
            raise ConfigError(
                f"dut `{dut_name}` does not implement framework `{requested}`\n"
                f"  implemented frameworks: {', '.join(implemented)}\n"
                "  (a DUT implements a framework by declaring a [frameworks.<name>] table "
                "in its sim config)"
            )
        selected = requested
    elif default_fw:
        selected = default_fw
    else:
        raise ConfigError(
            f"{path}: cannot determine the framework (implemented: {', '.join(implemented)}); "
            "set `default_framework` or pass --framework"
        )

    profile_overlay, profile_runtime = _framework_split(profile_sections.get(selected, {}))
    dut_overlay, dut_runtime = _framework_split(dut_sections.get(selected, {}))
    resolution_keys = {"frameworks", "default_framework"}
    profile_base = {key: value for key, value in profile_cfg.items() if key not in resolution_keys}
    dut_base = {key: value for key, value in data.items() if key not in resolution_keys}

    layers = [profile_base, profile_overlay, dut_base, dut_overlay]
    # `[sim].args` appends across every layer (all other inherited arrays replace,
    # except the target-table `defines` handled below).
    sim_args: list[str] = []
    for layer in layers:
        sim_args.extend(as_str_list(config_section(layer, "sim").get("args"), "sim.args"))
    merged: dict[str, Any] = {}
    for layer in layers:
        merged = deep_merge(merged, layer)
    if sim_args:
        merged["sim"] = {**config_section(merged, "sim"), "args": sim_args}

    # `defines` inside `[target_defaults.<t>]`/`[targets.<t>]` dedup-append across the four
    # layers, matching the `target_defaults` -> `targets` append in selected_target(): a
    # framework overlay contributes its gate define (e.g. the profile's `UVM`) on top of the
    # shared simulation set instead of replacing the list. Tool `flags` keep the plain
    # overlay-wins semantics — an overlay may zero a tool's flag list (the uvm
    # overlay relies on the vcs stage preamble for its flags).
    for section_name in ("target_defaults", "targets"):
        section = merged.get(section_name)
        if not isinstance(section, dict):
            continue
        rebuilt = dict(section)
        for target_name, target in section.items():
            if not isinstance(target, dict):
                continue
            combined: list[Any] = []
            seen = False
            for layer in layers:
                layer_section = layer.get(section_name)
                layer_target = (
                    layer_section.get(target_name) if isinstance(layer_section, dict) else None
                )
                values = layer_target.get("defines") if isinstance(layer_target, dict) else None
                if isinstance(values, list):
                    seen = True
                    for value in values:
                        if value not in combined:
                            combined.append(value)
            if seen:
                rebuilt[target_name] = {**target, "defines": combined}
        merged[section_name] = rebuilt

    runtime = deep_merge(profile_runtime, dut_runtime)
    if runtime:
        merged[selected] = runtime
    merged["framework"] = selected
    return merged, selected, implemented, default_fw


def merge_simulator_defaults(
    sim_cfg: dict[str, Any],
    simulators: dict[str, Any],
    tools: list[str],
) -> dict[str, Any]:
    """Apply simulator common defaults below the already profile-merged DUT config.

    Effective order for these tool adapter tables is:
    simulator ``[<tool>.build_defaults]`` / ``[<tool>.coverage_defaults]``
    < profile ``[build.<tool>]`` / ``[coverage.<tool>]``
    < DUT ``[build.<tool>]`` / ``[coverage.<tool>]``
    < CLI.
    """
    merged = deep_merge({}, sim_cfg)
    for tool in tools:
        sim_tool = simulators.get(tool, {})
        if not isinstance(sim_tool, dict):
            continue
        for section, default_key in (
            ("build", "build_defaults"),
            ("coverage", "coverage_defaults"),
        ):
            defaults = sim_tool.get(default_key, {})
            if defaults in ({}, None):
                continue
            if not isinstance(defaults, dict):
                raise ConfigError(f"simulators.toml: [{tool}.{default_key}] must be a table")

            section_cfg = config_section(merged, section) if section in merged else {}
            tool_cfg = section_cfg.get(tool, {})
            if tool_cfg in ({}, None):
                tool_cfg = {}
            if not isinstance(tool_cfg, dict):
                raise ConfigError(f"`{section}.{tool}` must be a table")

            new_section = dict(section_cfg)
            new_section[tool] = deep_merge(defaults, tool_cfg)
            merged[section] = new_section
    return merged


def load_profile(cfg_dir: Path, profile: str, flow_path: Path) -> dict[str, Any]:
    """Load a shared profile from the configs `profiles/<profile>.toml`.

    Profiles hold the settings common to a family of DUTs (stage tables, tool list, scheduler);
    a DUT's sim_cfg opts in via `profile = "<name>"` and its own keys override the profile's.
    """
    if not PROFILE_NAME_RE.match(profile):
        raise ConfigError(f"{flow_path}: invalid profile name `{profile}`")
    path = cfg_dir / "profiles" / f"{profile}.toml"
    if not path.is_file():
        raise ConfigError(f"{flow_path}: profile `{profile}` not found at {path}")
    data = load_toml(path)
    for key in ("name", "profile"):
        if key in data:
            raise ConfigError(f"{path}: a profile may not set `{key}`")
    return data


def _expand_source_lists(data: dict[str, Any], root: Path, where: str) -> None:
    """Expand ``[build].source_lists`` fragments into ``[build].incdirs``/``[build].sources``.

    Each entry is a repo-relative TOML fragment owned by the component it compiles (e.g. a
    shared VIP's ``uvm/sources.toml``): an ordered ``sources`` list plus the ``incdirs`` they
    need. Fragments expand in listed order AHEAD of the DUT's own incdirs/sources (dedup-merge),
    so the component layer compiles before the DUT layer that imports it; the consuming config
    keeps only its own files in ``[build].sources``. Fragment paths and every path a fragment
    lists must exist, so ``--validate-configs`` catches a stale manifest.
    """
    build = data.get("build")
    if not isinstance(build, dict) or "source_lists" not in build:
        return
    fragment_incdirs: list[str] = []
    fragment_sources: list[str] = []
    for text in as_str_list(build.get("source_lists"), "build.source_lists"):
        fragment_path = repo_path(root, text)
        if not fragment_path.is_file():
            raise ConfigError(f"{where}: [build].source_lists entry not found: {text}")
        fragment = load_toml(fragment_path)
        validate_allowed_keys(fragment, SOURCE_LIST_KEYS, str(fragment_path))
        for key, bucket in (("incdirs", fragment_incdirs), ("sources", fragment_sources)):
            for value in as_str_list(fragment.get(key), f"{fragment_path} `{key}`"):
                if not repo_path(root, value).exists():
                    raise ConfigError(f"{fragment_path}: `{key}` entry not found: {value}")
                if value not in bucket:
                    bucket.append(value)
    for key, expanded in (("incdirs", fragment_incdirs), ("sources", fragment_sources)):
        combined = _merge_unique_strings(expanded, as_str_list(build.get(key), f"build.{key}"))
        if combined:
            build[key] = combined


class OverlayFrameworkMismatch(ConfigError):
    """The adopter overlay's `frameworks` guard excludes the selected framework.

    A run treats this as a hard error (the user explicitly combined the overlay with a
    framework the overlay does not target); --validate-configs catches it to validate the
    non-targeted views without the overlay instead of failing them.
    """


def _append_unique(target: dict[str, Any], key: str, extra: list[str], where: str) -> None:
    combined = _merge_unique_strings(as_str_list(target.get(key), f"{where} `{key}`"), extra)
    if combined:
        target[key] = combined


_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env_vars(text: str, where: str, environ: Mapping[str, str] | None = None) -> str:
    """Expand ``$VAR`` / ``${VAR}`` in one adopter-overlay path from ``environ``.

    ``environ`` defaults to the process environment; the overlay applier passes that environment
    with the overlay's own ``[env]`` table applied on top. Only overlay-supplied ``[build]``
    entries pass through here: checked-in configs and the entries inside a ``source_lists``
    manifest stay literal (repo-relative or absolute). An unset variable is a
    :class:`ConfigError` naming the variable and the entry under ``where`` (the overlay file and
    key). A set-but-empty variable expands to the empty string, as in a shell.
    """
    source = os.environ if environ is None else environ

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        value = source.get(name)
        if value is None:
            raise ConfigError(f"{where}: environment variable `{name}` is not set (entry `{text}`)")
        return value

    return _ENV_VAR_RE.sub(substitute, text)


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_env_table(table: Any, where: str) -> dict[str, str]:
    """Validate a ``NAME = "value"`` environment table: shell-legal names, string values."""
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise ConfigError(f'{where}: must be a table of NAME = "value" pairs')
    env: dict[str, str] = {}
    for name, value in table.items():
        if not _ENV_NAME_RE.match(name):
            raise ConfigError(f"{where}: `{name}` is not a valid environment variable name")
        if not isinstance(value, str):
            raise ConfigError(f"{where}.{name}: value must be a string")
        env[name] = value
    return env


def _overlay_env_table(overlay: dict[str, Any], where: str) -> dict[str, str]:
    """Validate an overlay's ``[env]`` table: shell-legal variable names, string values."""
    return validate_env_table(overlay.get("env"), f"{where} [env]")


def activate_adopter_overlay_env(
    data: dict[str, Any], environ: MutableMapping[str, str] | None = None
) -> dict[str, str]:
    """Apply the overlay's ``[env]`` table to ``environ`` (the process environment by default).

    Every stage subprocess, ``env/`` snapshot, and in-process tool runner copies the process
    environment, so one application at run start reaches build and sim alike. An overlay value
    replaces an ambient one. Returns the applied table, empty when the view carries no overlay
    ``[env]``.
    """
    target = os.environ if environ is None else environ
    env = data.get("adopter_overlay_env")
    if not isinstance(env, dict) or not env:
        return {}
    applied = {str(name): str(value) for name, value in env.items()}
    target.update(applied)
    return applied


def apply_adopter_overlay(data: dict[str, Any], root: Path, overlay_path: Path) -> None:
    """Apply one adopter overlay file on top of the merged DUT view (append-only).

    The overlay is the runner-side equivalent of ocah.mk's adopter include hooks: it lets an
    adopter extend a build without editing checked-in configs (extra VIP packages, gate
    defines such as `OCAH_<PROTO>_VENDOR_IF`, factory-override run args). It is applied ONLY
    when `--overlay <path>` or `OCAH_DV_OVERLAY` names it — never auto-activated by the
    presence of an adopter checkout.

    Merge rules (all append-only, applied after the profile/DUT `[frameworks.<fw>]` merge and
    before `[build].source_lists` expansion, so an overlay-supplied manifest expands like a
    DUT-owned one):

    - `[build]` `incdirs`/`sources`/`source_lists`: `$VAR`/`${VAR}` expand from the process
      environment with the overlay's `[env]` applied on top (an unset variable is a config
      error), then dedup-append AFTER the DUT's own entries.
    - `[env]` (string values): validated and recorded under the reserved `adopter_overlay_env`
      key; the run path applies it to the process environment once, at run start, through
      :func:`activate_adopter_overlay_env`, where an overlay value replaces an ambient one.
      Loading never touches the environment, so `--validate-configs` and `--list` stay pure.
    - `[sim].args`: append after the merged `[sim].args` (still before run-mode/test/CLI args).
    - `[target_defaults.<t>]`/`[targets.<t>]` `defines`/`flags` and `[...tools.<tool>].flags`:
      dedup-append into the matching table (created when absent).
    - `frameworks = ["uvm", ...]` (optional): compatibility guard — applying the overlay to a
      view whose selected framework is not listed raises :class:`OverlayFrameworkMismatch`.

    Applying the same overlay to the same view is deterministic and repeatable: list order is
    preserved and the dedup rules make a re-application a no-op. The applied path and `[env]`
    table are recorded under the reserved `adopter_overlay` / `adopter_overlay_env` keys
    (surfaced in result.json as `overlay` / `overlay_env`).
    """
    where = f"adopter overlay {overlay_path}"
    if not overlay_path.is_file():
        raise ConfigError(f"adopter overlay not found: {overlay_path}")
    overlay = load_toml(overlay_path)
    validate_allowed_keys(overlay, ADOPTER_OVERLAY_KEYS, where)

    guard = overlay.get("frameworks")
    if guard is not None:
        guard_list = as_str_list(guard, f"{where} `frameworks`")
        if not guard_list:
            raise ConfigError(f"{where}: `frameworks` must be a non-empty list of framework names")
        selected = str(data.get("framework", ""))
        if selected not in guard_list:
            raise OverlayFrameworkMismatch(
                f"{where}: targets framework(s) {', '.join(guard_list)} but the selected view "
                f"is `{selected or '<none>'}`"
            )

    overlay_env = _overlay_env_table(overlay, where)
    # Path expansion resolves against the environment the stages run with once the table is
    # activated.
    expansion_env: dict[str, str] = {**os.environ, **overlay_env}

    build_overlay = config_section(overlay, "build")
    if build_overlay:
        validate_allowed_keys(build_overlay, ADOPTER_OVERLAY_BUILD_KEYS, f"{where} [build]")
        build = data.setdefault("build", {})
        if not isinstance(build, dict):
            raise ConfigError(f"{where}: merged [build] is not a table")
        for key in ("incdirs", "sources", "source_lists"):
            key_where = f"{where} build.{key}"
            extra = [
                expand_env_vars(text, key_where, expansion_env)
                for text in as_str_list(build_overlay.get(key), key_where)
            ]
            if extra:
                _append_unique(build, key, extra, f"{where} merged build")

    sim_overlay = config_section(overlay, "sim")
    if sim_overlay:
        validate_allowed_keys(sim_overlay, ADOPTER_OVERLAY_SIM_KEYS, f"{where} [sim]")
        extra_args = as_str_list(sim_overlay.get("args"), f"{where} sim.args")
        if extra_args:
            sim = config_section(data, "sim")
            data["sim"] = {
                **sim,
                "args": [*as_str_list(sim.get("args"), "sim.args"), *extra_args],
            }

    for section_name in ("target_defaults", "targets"):
        section_overlay = overlay.get(section_name)
        if section_overlay is None:
            continue
        if not isinstance(section_overlay, dict):
            raise ConfigError(f"{where}: [{section_name}] must hold per-target tables")
        section = data.setdefault(section_name, {})
        for target_name, target_overlay in section_overlay.items():
            target_where = f"{where} [{section_name}.{target_name}]"
            if not isinstance(target_overlay, dict):
                raise ConfigError(f"{target_where}: must be a table")
            validate_allowed_keys(target_overlay, ADOPTER_OVERLAY_TARGET_KEYS, target_where)
            target = section.setdefault(target_name, {})
            for key in ("defines", "flags"):
                extra = as_str_list(target_overlay.get(key), f"{target_where} `{key}`")
                if extra:
                    _append_unique(target, key, extra, target_where)
            tools_overlay = target_overlay.get("tools")
            if tools_overlay is None:
                continue
            if not isinstance(tools_overlay, dict):
                raise ConfigError(f"{target_where}: `tools` must hold per-tool tables")
            tools = target.setdefault("tools", {})
            for tool_name, tool_overlay in tools_overlay.items():
                tool_where = f"{target_where} tools.{tool_name}"
                if not isinstance(tool_overlay, dict):
                    raise ConfigError(f"{tool_where}: must be a table")
                validate_allowed_keys(tool_overlay, TARGET_TOOL_KEYS, tool_where)
                extra = as_str_list(tool_overlay.get("flags"), f"{tool_where} `flags`")
                if extra:
                    _append_unique(tools.setdefault(tool_name, {}), "flags", extra, tool_where)

    data["adopter_overlay"] = repo_rel(root, overlay_path)
    if overlay_env:
        data["adopter_overlay_env"] = overlay_env


def load_dut(
    path: Path,
    cfg_dir: Path,
    *,
    root: Path,
    name: str,
    root_rel: str,
    framework: str | None = None,
    adopter_overlay: Path | None = None,
) -> Dut:
    """Load a merged per-DUT ``<dut>_sim_cfg.toml`` (selected by the duts resolver).

    The file carries the DUT's own keys (``name``/``kind``/``description``/``[testlist]``/stage
    overrides) plus the build/cocotb/coverage/targets tables, and opts into a shared stage graph
    with ``profile = "<name>"``. ``name`` is the bare DUT name and ``root_rel`` the repo-relative
    DUT DV root, both supplied by the resolver.
    """
    data = load_toml(path)

    implemented_frameworks: list[str] = []
    default_framework = ""
    frameworks_aware = False
    profile = data.get("profile")
    if profile is not None:
        if not isinstance(profile, str) or not profile:
            raise ConfigError(f"{path}: `profile` must be a non-empty string")
        profile_cfg = load_profile(cfg_dir, profile, path)
        if framework_sections(profile_cfg, f"profile `{profile}`"):
            # Frameworks-aware profile: the DUT declares what it implements as
            # `[frameworks.<fw>]` tables and the loader merges the selected framework's layers.
            frameworks_aware = True
            data, _selected, implemented_frameworks, default_framework = _merge_framework_config(
                profile_cfg, data, path, profile, requested=framework
            )
        else:
            if "frameworks" in data or "default_framework" in data:
                raise ConfigError(
                    f"{path}: profile `{profile}` declares no [frameworks.<name>] sections, so "
                    "this DUT cannot declare frameworks"
                )
            # Single-framework profile (no [frameworks.<name>] sections): `[sim].args` appends
            # across profile->DUT inheritance (every other inherited array replaces). Capture both
            # lists before deep_merge clobbers the DUT's, then re-join.
            dut_sim_args = as_str_list(config_section(data, "sim").get("args"), "sim.args")
            profile_sim_args = as_str_list(
                config_section(profile_cfg, "sim").get("args"), "sim.args"
            )
            data = deep_merge(profile_cfg, data)
            combined_sim_args = profile_sim_args + dut_sim_args
            if combined_sim_args:
                data["sim"] = {**config_section(data, "sim"), "args": combined_sim_args}

    for reserved in ("adopter_overlay", "adopter_overlay_env"):
        if reserved in data:
            raise ConfigError(
                f"{path}: `{reserved}` may not be set in a sim config or profile — the adopter "
                "overlay layer activates only via --overlay or OCAH_DV_OVERLAY"
            )
    if adopter_overlay is not None:
        # After the framework merge (the overlay extends the selected view) and before
        # source-list expansion (an overlay-supplied manifest expands like a DUT-owned one).
        apply_adopter_overlay(data, root, adopter_overlay)

    # Post-merge, so a framework overlay's [frameworks.<fw>.build].source_lists is visible.
    _expand_source_lists(data, root, str(path))

    file_name = data.get("name")
    kind = data.get("kind")
    default_tool = data.get("default_tool", "")
    tools = as_str_list(data.get("tools"), "tools")

    if not isinstance(file_name, str) or not file_name:
        raise ConfigError(f"{path}: missing required string `name`")
    if file_name != name:
        raise ConfigError(
            f"{path}: `name` is `{file_name}` but the resolved DUT is `{name}` — "
            "the sim_cfg `name` must match the DUT directory/registry entry"
        )
    if kind not in {"dv", "fv", "acceptance"}:
        raise ConfigError(f"{path}: `kind` must be dv, fv, or acceptance")
    if default_tool and default_tool not in tools:
        raise ConfigError(f"{path}: `default_tool` must be listed in `tools`")

    selected_framework = str(data.get("framework", ""))
    if framework and not frameworks_aware:
        raise ConfigError(
            f"dut `{name}` does not support framework selection "
            "(its profile declares no [frameworks.<name>] sections)"
        )
    return Dut(
        name=name,
        kind=str(kind),
        description=str(data.get("description", "")),
        framework=selected_framework,
        visibility=str(data.get("visibility", "public")),
        runnability=str(data.get("runnability", "contributor")),
        license=str(data.get("license", "none")),
        root=root_rel,
        default_tool=str(default_tool),
        tools=tools,
        path=path,
        raw=data,
        frameworks=implemented_frameworks or ([selected_framework] if selected_framework else []),
        default_framework=default_framework or selected_framework,
    )


def validate_simulator_registry(simulators: dict[str, Any], where: str) -> None:
    """Validate a tool registry: checked-in, or checked-in with a site layer merged in."""
    for tool, table in simulators.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{where}: [{tool}] must be a table")
        kind = table.get("kind")
        if kind not in TOOL_KINDS:
            raise ConfigError(
                f"{where}: [{tool}].kind must be one of {', '.join(sorted(TOOL_KINDS))}"
            )
        if not isinstance(table.get("binary", tool), str) or not table.get("binary", tool):
            raise ConfigError(f"{where}: [{tool}].binary must be a non-empty string")
        frameworks = as_str_list(table.get("frameworks"), f"{where} [{tool}].frameworks")
        if not frameworks:
            raise ConfigError(
                f"{where}: [{tool}] must declare `frameworks` (the frameworks this tool can run)"
            )
        if "license_env" not in table:
            raise ConfigError(
                f"{where}: [{tool}] must declare `license_env` ([] for a license-free tool)"
            )
        as_str_list(table.get("license_env"), f"{where} [{tool}].license_env")
        min_version = table.get("min_version")
        if min_version is not None and not (
            isinstance(min_version, str) and MIN_VERSION_RE.fullmatch(min_version)
        ):
            raise ConfigError(
                f'{where}: [{tool}].min_version must be a dotted release number such as "5.036"'
            )
        if kind == "formal":
            if "argv" not in table:
                raise ConfigError(
                    f"{where}: [{tool}] is a formal backend and must carry an `argv` launch template"
                )
            validate_formal_argv_template(table["argv"], f"{where} [{tool}].argv")
        elif "argv" in table:
            raise ConfigError(
                f"{where}: [{tool}].argv is a formal launch template; `{tool}` is kind `{kind}`"
            )
        coverage_defaults = table.get("coverage_defaults")
        if coverage_defaults is None:
            continue
        if not isinstance(coverage_defaults, dict):
            raise ConfigError(f"{where}: [{tool}.coverage_defaults] must be a table")
        validate_coverage_tool_table(
            coverage_defaults,
            f"{where} [{tool}.coverage_defaults]",
            require_complete=True,
        )
        supported = as_str_list(table.get("supports_cov"), f"{where} [{tool}].supports_cov")
        if not any(
            metric in {"line", "toggle", "branch", "fsm", "functional"} for metric in supported
        ):
            raise ConfigError(
                f"{where}: [{tool}] declares coverage defaults but no normalized coverage metric"
            )


def load_simulators(root: Path) -> dict[str, Any]:
    """The checked-in tool registry; ``runlib.site.merged_simulators`` layers a site file on it."""
    path = configs_root(root) / "simulators.toml"
    if not path.is_file():
        raise ConfigError(f"missing simulator registry: {path}")
    data = load_toml(path)
    simulators = {key: value for key, value in data.items() if key != "schema_version"}
    validate_simulator_registry(simulators, str(path))
    for tool, table in simulators.items():
        site_only = sorted(set(table) & SITE_ONLY_TOOL_KEYS)
        if site_only:
            raise ConfigError(
                f"{path}: [{tool}] carries deployment key(s) {', '.join(site_only)}; "
                "they belong in the site layer (site.local.toml)"
            )
    return simulators


def validate_executor_registry(executors: dict[str, Any], where: str) -> None:
    """Validate an executor registry: checked-in, or checked-in with a site layer merged in."""
    if "local" not in executors:
        raise ConfigError(f"{where}: missing required [local] executor")
    for name, cfg in executors.items():
        if not isinstance(cfg, dict):
            raise ConfigError(f"{where}: [{name}] must be a table")
        kind = cfg.get("kind")
        if kind == "local":
            validate_allowed_keys(cfg, LOCAL_EXECUTOR_KEYS, f"{where} [{name}]")
            if cfg.get("submit_argv") not in ([], None):
                raise ConfigError(f"{where}: [local].submit_argv must be []")
            if cfg.get("wait_mode") != "inline":
                raise ConfigError(f"{where}: [local].wait_mode must be `inline`")
        elif kind == "cluster" and "driver" in cfg:
            validate_cluster_executor(cfg, f"{where} [{name}]")
        elif kind == "cluster":
            validate_allowed_keys(cfg, CLUSTER_EXECUTOR_V1_KEYS, f"{where} [{name}]")
            if not isinstance(cfg.get("binary"), str) or not cfg.get("binary"):
                raise ConfigError(f"{where}: [{name}].binary must be a non-empty string")
            as_str_list(cfg.get("submit_argv"), f"{name}.submit_argv")
            as_str_list(cfg.get("env_passthrough"), f"{name}.env_passthrough")
            validate_placeholders_in_value(
                cfg.get("submit_argv", []), f"{where} [{name}].submit_argv"
            )
        else:
            raise ConfigError(f"{where}: [{name}].kind must be `local` or `cluster`")


def validate_cluster_executor(cfg: dict[str, Any], where: str) -> None:
    """A schema-2 cluster table: a driver, the binaries it runs, and its argv templates."""
    validate_allowed_keys(cfg, CLUSTER_EXECUTOR_KEYS, where)
    driver = cfg.get("driver")
    if driver not in CLUSTER_DRIVERS:
        raise ConfigError(f"{where}.driver must be one of: {', '.join(sorted(CLUSTER_DRIVERS))}")
    binaries = as_str_list(cfg.get("binaries"), f"{where}.binaries")
    if not binaries or not all(binaries):
        raise ConfigError(f"{where}.binaries must name every scheduler command the driver runs")
    if cfg.get("wait_mode", "poll") != "poll":
        raise ConfigError(f"{where}.wait_mode must be `poll` on a cluster executor")
    for key, allowed in EXECUTOR_TEMPLATE_PLACEHOLDERS.items():
        validate_argv_template(
            cfg.get(key),
            f"{where}.{key}",
            allowed,
            required=key in {"submit_argv", "query_argv", "cancel_argv"},
        )
    for name in as_str_list(cfg.get("env_passthrough"), f"{where}.env_passthrough"):
        if not ENV_NAME_RE.match(name):
            raise ConfigError(f"{where}.env_passthrough: {name!r} is not a variable name")
    if "defaults" in cfg:
        validate_resource_table(cfg["defaults"], f"{where}.defaults")
    if "build_defaults" in cfg:
        validate_resource_table(cfg["build_defaults"], f"{where}.build_defaults")
    if "builds" in cfg and cfg["builds"] not in EXECUTOR_BUILD_MODES:
        raise ConfigError(
            f"{where}.builds must be one of: {', '.join(sorted(EXECUTOR_BUILD_MODES))}"
        )
    if "limits" in cfg:
        validate_limits_table(cfg["limits"], f"{where}.limits")
    for key in ("description", "history_parser", "setup_hook"):
        if key in cfg and (not isinstance(cfg[key], str) or not cfg[key]):
            raise ConfigError(f"{where}.{key} must be a non-empty string")
    if "arrays" in cfg and not isinstance(cfg["arrays"], bool):
        raise ConfigError(f"{where}.arrays must be true or false")


def load_executors(root: Path) -> dict[str, Any]:
    """The checked-in executor registry; ``runlib.site.merged_executors`` layers a site file on it."""
    path = configs_root(root) / "executors.toml"
    if not path.is_file():
        raise ConfigError(f"missing executor registry: {path}")
    data = load_toml(path)
    if data.get("schema_version") not in EXECUTOR_SCHEMA_VERSIONS:
        raise ConfigError(
            f"{path}: schema_version must be one of "
            + ", ".join(str(version) for version in sorted(EXECUTOR_SCHEMA_VERSIONS))
        )
    executors = {key: value for key, value in data.items() if key != "schema_version"}
    validate_executor_registry(executors, str(path))
    for name, table in executors.items():
        site_only = sorted(set(table) & SITE_ONLY_EXECUTOR_KEYS)
        if site_only:
            raise ConfigError(
                f"{path}: [{name}] carries deployment key(s) {', '.join(site_only)}; "
                "they belong in the site layer (site.local.toml)"
            )
    return executors


def load_sim_cfg(flow: Dut, root: Path) -> dict[str, Any]:
    # The sim_cfg tables live in the DUT config file, so the loaded DUT already holds them.
    return flow.raw


def build_cfg(flow: Flow, sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return (
        config_section(sim_cfg, "build")
        if "build" in sim_cfg
        else config_section(flow.raw, "build")
    )


def cocotb_cfg(flow: Flow, sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return (
        config_section(sim_cfg, "cocotb")
        if "cocotb" in sim_cfg
        else config_section(flow.raw, "cocotb")
    )


def defaults_cfg(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return config_section(sim_cfg, "defaults") if "defaults" in sim_cfg else {}


def run_modes_cfg(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    """The effective ``[run_modes]`` table (profile entries deep-merged under the DUT's)."""
    return config_section(sim_cfg, "run_modes") if "run_modes" in sim_cfg else {}


def coverage_cfg(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return config_section(sim_cfg, "coverage") if "coverage" in sim_cfg else {}


def c_build_cfg(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return config_section(sim_cfg, "c_build") if "c_build" in sim_cfg else {}


def tool_coverage_cfg(sim_cfg: dict[str, Any], tool: str) -> dict[str, Any]:
    """The per-tool `[coverage.<tool>]` subtable (build/sim coverage args for that backend)."""
    cov = coverage_cfg(sim_cfg)
    value = cov.get(tool, {})
    return value if isinstance(value, dict) else {}


def default_target_name(sim_cfg: dict[str, Any]) -> str:
    return str(defaults_cfg(sim_cfg).get("target", "default"))


def target_names(sim_cfg: dict[str, Any]) -> set[str]:
    targets = config_section(sim_cfg, "targets") if "targets" in sim_cfg else {}
    return {
        name for name, value in targets.items() if isinstance(name, str) and isinstance(value, dict)
    }


def resolved_target_name(sim_cfg: dict[str, Any], test: TestEntry | None) -> str:
    return test.target if test and test.target else default_target_name(sim_cfg)


def selected_target(sim_cfg: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    """The active `[targets.<name>]` table (defines + per-tool flags + build_dir).

    One `[targets]` table serves compile and run; `[defaults].target` selects the entry.
    """
    name = name or default_target_name(sim_cfg)
    target_defaults = (
        config_section(sim_cfg, "target_defaults") if "target_defaults" in sim_cfg else {}
    )
    target_default = (
        target_defaults.get(name, target_defaults.get("default", {}))
        if isinstance(target_defaults, dict)
        else {}
    )
    if target_default and not isinstance(target_default, dict):
        raise ConfigError(f"`target_defaults.{name}` must be a table")
    targets = config_section(sim_cfg, "targets") if "targets" in sim_cfg else {}
    target = targets.get(name, {}) if isinstance(targets, dict) else {}
    if target and not isinstance(target, dict):
        raise ConfigError(f"`targets.{name}` must be a table")
    if not target_default:
        return target if isinstance(target, dict) else {}
    merged = deep_merge(target_default, target if isinstance(target, dict) else {})
    for key in ("defines", "flags"):
        default_values = target_default.get(key)
        target_values = target.get(key) if isinstance(target, dict) else None
        if isinstance(default_values, list) and isinstance(target_values, list):
            combined: list[Any] = []
            for value in [*default_values, *target_values]:
                if value not in combined:
                    combined.append(value)
            merged[key] = combined

    default_tools = target_default.get("tools", {}) if isinstance(target_default, dict) else {}
    target_tools = target.get("tools", {}) if isinstance(target, dict) else {}
    if isinstance(default_tools, dict) and isinstance(target_tools, dict):
        merged_tools = merged.setdefault("tools", {})
        if isinstance(merged_tools, dict):
            for tool, default_tool_cfg in default_tools.items():
                if not isinstance(default_tool_cfg, dict):
                    continue
                target_tool_cfg = target_tools.get(tool, {})
                if not isinstance(target_tool_cfg, dict):
                    continue
                default_flags = default_tool_cfg.get("flags")
                target_flags = target_tool_cfg.get("flags")
                if isinstance(default_flags, list) and isinstance(target_flags, list):
                    tool_cfg = dict(merged_tools.get(tool, {}))
                    combined_flags: list[Any] = []
                    for value in [*default_flags, *target_flags]:
                        if value not in combined_flags:
                            combined_flags.append(value)
                    tool_cfg["flags"] = combined_flags
                    merged_tools[tool] = tool_cfg
    return merged


def _merge_unique_strings(base: list[str], overlay: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*base, *overlay]:
        if value not in merged:
            merged.append(value)
    return merged


def targeted_sim_cfg(
    sim_cfg: dict[str, Any],
    target_name: str,
    *,
    force_target_filelist: bool = False,
) -> dict[str, Any]:
    """Return a cloned config resolved for one target.

    Stage implementations consume source-selection fields from `[build]`, while target policy lives
    under `[targets.<name>]`; the clone copies target-owned source selectors into `[build]` and
    sets `[defaults].target`.
    """
    cfg = copy.deepcopy(sim_cfg)
    cfg.setdefault("defaults", {})["target"] = target_name

    target = selected_target(cfg, target_name)
    build = cfg.setdefault("build", {})
    if not isinstance(build, dict):
        raise ConfigError("[build] must be a table")
    source_selectors = ("bender_targets", "stubs", "sources", "exclude_files")
    target_changes_sources = any(key in target for key in source_selectors)

    # Bender target sets are target-specific compile views, so a target table overrides the generic
    # build target list. Common bender targets stay in `[build].common_bender_targets`.
    if "bender_targets" in target:
        build["bender_targets"] = as_str_list(
            target.get("bender_targets"), f"targets.{target_name}.bender_targets"
        )

    # These source lists are additive: DUT-wide sources from `[build]` plus target-owned shims/stubs.
    # `exclude_files` is likewise additive: DUT-wide drops from `[build]` plus target-owned drops
    # (e.g. a CPU-stub target excludes the real hw/sys/sep/rtl/sep_cpu.sv so its appended stub
    # is the only definition, with all DUT packages already declared ahead of it).
    for key in ("stubs", "sources", "exclude_files"):
        if key in target:
            build[key] = _merge_unique_strings(
                as_str_list(build.get(key), f"build.{key}"),
                as_str_list(target.get(key), f"targets.{target_name}.{key}"),
            )

    # Target-specific filelist paths win. Otherwise, derive generated filelists under the target
    # build root whenever a target changes source selection, or when a caller forces target scoping.
    # This keeps even a single non-default target from overwriting the shared DUT filelist with a
    # different source set that a later run-only/build-only invocation could accidentally consume.
    for key in ("filelist", "bender_filelist"):
        if key in target:
            value = target.get(key)
            if not isinstance(value, str) or not value:
                raise ConfigError(f"`targets.{target_name}.{key}` must be a non-empty string")
            build[key] = value

    if force_target_filelist or target_changes_sources:
        build_dir = target.get("build_dir")
        if not isinstance(build_dir, str) or not build_dir:
            raise ConfigError(f"`targets.{target_name}.build_dir` must be a non-empty string")
        # Per-target subdir so targets that share one build_dir do not clobber each other's
        # generated filelist: a shared filelists/{bender,files}.f is last-writer-wins, so a
        # multi-target regression would compile a later target's source set (e.g. the real
        # sep_cpu in place of a CPU-stub target's stub).
        filelist_root = Path(build_dir) / "filelists" / target_name
        work_dir = target.get("work_dir", build_dir)
        if not isinstance(work_dir, str) or not work_dir:
            raise ConfigError(
                f"`targets.{target_name}.work_dir` must be a non-empty string when provided"
            )
        build["work_dir"] = work_dir
        if "bender_filelist" not in target:
            build["bender_filelist"] = str(filelist_root / "bender.f")
        if "filelist" not in target:
            build["filelist"] = str(filelist_root / "files.f")

    return cfg


def target_tool_cfg(target: dict[str, Any], tool: str) -> dict[str, Any]:
    tools = target.get("tools", {})
    if not isinstance(tools, dict):
        raise ConfigError("target.tools must be a table")
    value = tools.get(tool, {})
    if not isinstance(value, dict):
        raise ConfigError(f"target.tools.{tool} must be a table")
    return value


def target_flags(target: dict[str, Any], tool: str) -> list[str]:
    """Target-level simulator flags: shared ``flags`` then ``tools.<tool>.flags``.

    Each list item is one argv token. The simulators run through cocotb's Python runner
    and subprocess argv lists, so a token such as ``"-assert svaext"`` reaches the tool as one
    argument that it silently ignores (VCS: ``Ignoring unknown option '-assert'``) instead of
    being shell-split; such an item is a config error, not a quiet no-op.
    """
    flags = [
        *config_list(target, "flags"),
        *as_str_list(target_tool_cfg(target, tool).get("flags"), f"target.tools.{tool}.flags"),
    ]
    for flag in flags:
        if any(ch.isspace() for ch in flag):
            raise ConfigError(
                f"target flag {flag!r} contains whitespace; write each argument as its own list "
                'item (for example ["-assert", "svaext"])'
            )
    return flags


# One target table serves both compile and run; these accessors let stage code that distinguishes
# compile from run resolve the same target.
def selected_compile_target(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return selected_target(sim_cfg)


def selected_run_target(sim_cfg: dict[str, Any]) -> dict[str, Any]:
    return selected_target(sim_cfg)


def validate_run_mode_request(sim_cfg: dict[str, Any], requested: str, where: str) -> None:
    """Reject a run-mode name that is not an effective ``[run_modes]`` entry.

    ``where`` names the reference's source (``--run-mode``, a testlist entry, or
    ``[defaults].run_mode``) so the error points at the thing to fix.
    """
    modes = run_modes_cfg(sim_cfg)
    if str(requested) not in modes:
        allowed = ", ".join(sorted(modes)) if modes else "none defined"
        raise ConfigError(f"{where}: unknown run mode `{requested}` (allowed: {allowed})")


def selected_run_mode(sim_cfg: dict[str, Any], test: TestEntry | None, args: Any) -> dict[str, Any]:
    requested = args.run_mode
    where = "--run-mode"
    if not requested and test and test.run_modes:
        requested = test.run_modes[0]
        where = f"test `{test.name}` run_modes"
    if not requested:
        # The implicit fallback is optional: a DUT whose tests all carry run_modes
        # never consults it, and a DUT without a `smoke` mode must still resolve (to no mode).
        requested = defaults_cfg(sim_cfg).get("run_mode", "smoke")
        mode = run_modes_cfg(sim_cfg).get(str(requested), {})
        return mode if isinstance(mode, dict) else {}
    # Explicit references were already validated before stage execution (catalog load checks
    # testlist and [defaults] names, the CLI entry checks --run-mode); this re-check keeps
    # direct API callers on the same contract.
    validate_run_mode_request(sim_cfg, str(requested), where)
    return run_modes_cfg(sim_cfg)[str(requested)]


def _test_from_dict(entry: dict[str, Any], source: Path | None) -> TestEntry:
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        where = f"{source}: " if source else ""
        raise ConfigError(f"{where}test entry missing required string `name`")
    firmware = entry.get("firmware")
    if firmware is not None and not isinstance(firmware, (str, dict)):
        where = f"{source}: " if source else ""
        raise ConfigError(f"{where}{name}.firmware must be a string or table")
    target = entry.get("target")
    if target is not None and (not isinstance(target, str) or not target):
        where = f"{source}: " if source else ""
        raise ConfigError(f"{where}{name}.target must be a non-empty string")
    where = f"{source}: " if source else ""
    expect_fail = entry.get("expect_fail")
    if expect_fail is not None and (not isinstance(expect_fail, str) or not expect_fail.strip()):
        raise ConfigError(
            f"{where}{name}.expect_fail must be a non-empty string recording why the leaf "
            "fails on the current DUT (the defect it reproduces)"
        )
    expect_fail_match = entry.get("expect_fail_match")
    if expect_fail_match is not None:
        if not isinstance(expect_fail_match, str) or not expect_fail_match.strip():
            raise ConfigError(f"{where}{name}.expect_fail_match must be a non-empty regex string")
        if expect_fail is None:
            raise ConfigError(f"{where}{name}.expect_fail_match requires expect_fail")
        try:
            re.compile(expect_fail_match)
        except re.error as exc:
            raise ConfigError(
                f"{where}{name}.expect_fail_match is not a valid regex: {exc}"
            ) from exc

    # `module` is either a bare string (bound to the DUT's default framework) or a per-framework
    # binding map `{ cocotb = "...", uvm = "..." }`. A map value of `false` declares the
    # framework out of scope for the scenario. Resolution against the selected framework
    # happens at catalog load, where the flow is known.
    raw_module = entry.get("module", name)
    bindings: dict[str, str] = {}
    excluded: set[str] = set()
    if isinstance(raw_module, dict):
        for fw, value in raw_module.items():
            if not isinstance(fw, str) or not FRAMEWORK_NAME_RE.match(fw):
                raise ConfigError(f"{where}{name}.module has an invalid framework key `{fw}`")
            if value is False:
                excluded.add(fw)
            elif isinstance(value, str) and value:
                bindings[fw] = value
            else:
                raise ConfigError(
                    f"{where}{name}.module.{fw} must be a non-empty string or `false`"
                )
        if not bindings:
            raise ConfigError(f"{where}{name}.module must declare at least one framework binding")
        module = ""
    elif isinstance(raw_module, str) and raw_module:
        module = raw_module
    else:
        raise ConfigError(f"{where}{name}.module must be a non-empty string or a binding table")

    # `tools = []` names no simulator that could ever run the scenario, which is a way
    # of deleting a test without saying so. Caught here, where an absent key is still
    # distinguishable from an explicitly empty one -- as_str_list flattens both to [].
    if "tools" in entry and not entry["tools"]:
        raise ConfigError(
            f"{where}{name}.tools is empty, so no tool could ever run this scenario; "
            f"drop the key to allow every tool, or name the ones that work"
        )

    overrides_raw = entry.get("overrides", {})
    overrides: dict[str, dict[str, Any]] = {}
    if not isinstance(overrides_raw, dict):
        raise ConfigError(
            f"{where}{name}.overrides must be a table of [tests.overrides.<framework>]"
        )
    for fw, table in overrides_raw.items():
        if not isinstance(fw, str) or not FRAMEWORK_NAME_RE.match(fw):
            raise ConfigError(f"{where}{name}.overrides has an invalid framework key `{fw}`")
        if not isinstance(table, dict):
            raise ConfigError(f"{where}{name}.overrides.{fw} must be a table")
        validate_allowed_keys(table, TEST_OVERRIDE_KEYS, f"{where}{name}.overrides.{fw}")
        as_int(table.get("seed"), f"{name}.overrides.{fw}.seed")
        as_int(table.get("timeout_sec"), f"{name}.overrides.{fw}.timeout_sec")
        as_str_list(table.get("args"), f"{name}.overrides.{fw}.args")
        overrides[fw] = table

    return TestEntry(
        name=name,
        module=module,
        bindings=bindings,
        excluded=frozenset(excluded),
        overrides=overrides,
        target=target,
        seed=as_int(entry.get("seed"), f"{name}.seed"),
        reseed=as_int(entry.get("reseed"), f"{name}.reseed"),
        timeout_sec=as_int(entry.get("timeout_sec"), f"{name}.timeout_sec"),
        tags=as_str_list(entry.get("tags"), f"{name}.tags"),
        run_modes=as_str_list(entry.get("run_modes"), f"{name}.run_modes"),
        tools=as_str_list(entry.get("tools"), f"{name}.tools"),
        args=as_str_list(entry.get("args"), f"{name}.args"),
        firmware=firmware,
        expect_fail=expect_fail,
        expect_fail_match=expect_fail_match,
        source=source,
    )


def _resolve_catalog_frameworks(flow: Flow, tests: dict[str, TestEntry], source: Path) -> None:
    """Resolve each scenario's `module` binding and apply per-framework overrides.

    A bare-string `module` is normalized to a binding for the DUT's default framework; a binding
    map is looked up by the selected framework. A scenario with no binding for the selected
    framework keeps `module = ""`; selection decides before it can run: a framework the map
    declares `false` is skipped from group and tag selections, a framework the map omits is an
    error unless --skip-unimplemented is given.
    """
    if not flow.framework:
        for test in tests.values():
            if test.bindings:
                raise ConfigError(
                    f"{source}: test `{test.name}` uses a per-framework module binding map, "
                    "but this DUT has no framework"
                )
        return
    implemented = set(flow.frameworks)
    for test in tests.values():
        for label, keys in (
            ("module binding(s)", test.bindings),
            ("exclusion(s)", test.excluded),
            ("override(s)", test.overrides),
        ):
            unknown = sorted(set(keys) - implemented)
            if unknown:
                raise ConfigError(
                    f"{source}: test `{test.name}` declares {label} for framework(s) this DUT "
                    f"does not implement: {', '.join(unknown)} "
                    f"(implemented: {', '.join(flow.frameworks)})"
                )
        if test.bindings:
            test.module = test.bindings.get(flow.framework, "")
        else:
            default = flow.default_framework or flow.framework
            test.bindings = {default: test.module}
            if flow.framework != default:
                test.module = ""
        override = test.overrides.get(flow.framework, {})
        if "seed" in override:
            test.seed = as_int(override.get("seed"), f"{test.name}.overrides.seed")
        if "timeout_sec" in override:
            test.timeout_sec = as_int(
                override.get("timeout_sec"), f"{test.name}.overrides.timeout_sec"
            )
        if "args" in override:
            # Override args append after the scenario's own args (run-stage layering).
            test.args = [
                *(test.args or []),
                *as_str_list(override.get("args"), f"{test.name}.overrides.args"),
            ]


def _validate_run_mode_references(flow: Flow, tests: dict[str, TestEntry]) -> None:
    """Every explicit run-mode reference must name an effective ``[run_modes]`` entry.

    Runs after include expansion, so a reference is checked no matter which included file
    declares it. Covers per-test ``run_modes`` lists and an explicit ``[defaults].run_mode``;
    an unknown name would otherwise resolve to an empty mode and silently drop the mode's
    args and timeout.
    """
    known = set(run_modes_cfg(flow.raw))
    for test in tests.values():
        for mode in test.run_modes or []:
            if mode not in known:
                where = f"{test.source or flow.path}: test `{test.name}`"
                validate_run_mode_request(flow.raw, mode, where)
    default = defaults_cfg(flow.raw).get("run_mode")
    if default is not None:
        validate_run_mode_request(flow.raw, str(default), f"{flow.path}: [defaults].run_mode")


def _validate_tool_references(flow: Flow, tests: dict[str, TestEntry]) -> None:
    """Every per-test ``tools`` entry must name a simulator the DUT declares.

    Runs after include expansion, like the run-mode check beside it. A name the DUT does
    not declare could never match the selected tool, so the scenario would be skipped on
    every run -- silently, and for a typo. An empty list means unrestricted, the same way
    an absent ``tags`` or ``run_modes`` does; an explicitly empty one is rejected at
    parse time, where it is still distinguishable from an absent key.
    """
    for test in tests.values():
        if not test.tools or not test.module:
            # No binding for the selected framework means this view never runs the
            # scenario at all (see _resolve_catalog_frameworks), so which simulators it
            # would need is not this view's business -- and a framework overlay may
            # legitimately declare a narrower `tools` list than the tool the scenario names.
            continue
        where = f"{test.source or flow.path}: test `{test.name}`"
        unknown = [name for name in test.tools if name not in flow.tools]
        if unknown:
            raise ConfigError(
                f"{where}: `tools` names {', '.join(f'`{n}`' for n in unknown)}, which "
                f"dut `{flow.name}` does not declare (declares: {', '.join(flow.tools)})"
            )


def _validate_group_members(
    tests: dict[str, TestEntry], groups: dict[str, list[str]], group_sources: dict[str, Path]
) -> None:
    """Every group member must name a test defined after include expansion.

    An unresolved member would otherwise survive selection and surface at runtime as a
    KeyError when the plan indexes the catalog. Only existence is checked: a test may be
    a member of any number of groups, and a group may list tests declared in other files.
    """
    for name, members in groups.items():
        missing = [member for member in members if member not in tests]
        if missing:
            raise ConfigError(
                f"{group_sources[name]}: group `{name}` references missing test(s): "
                f"{', '.join(missing)}"
            )


def load_test_catalog(flow: Flow, root: Path) -> TestCatalog:
    testlist = flow.raw.get("testlist", {})
    if isinstance(testlist, dict) and testlist.get("path"):
        raw_path = Path(str(testlist["path"])).expanduser()
        path = raw_path if raw_path.is_absolute() else root / raw_path
        if not path.is_file() and not raw_path.is_absolute():
            # A relative testlist path may be repo-relative or DUT-local; repo-relative wins.
            path = flow.path.parent / raw_path
        tests, groups, group_sources = _merge_testlist_data(
            load_toml(path), path, path.parent, root, [path]
        )
        _resolve_catalog_frameworks(flow, tests, path)
        _validate_run_mode_references(flow, tests)
        _validate_tool_references(flow, tests)
        _validate_group_members(tests, groups, group_sources)
        return TestCatalog(path=path, tests=tests, groups=groups)
    # No separate testlist file: read inline [[tests]]/[[groups]] from the flow TOML.
    tests, groups, group_sources = _merge_testlist_data(
        flow.raw,
        flow.path,
        flow.path.parent,
        root,
        [flow.path],
        validate_testlist_keys=False,
    )
    _resolve_catalog_frameworks(flow, tests, flow.path)
    _validate_run_mode_references(flow, tests)
    _validate_tool_references(flow, tests)
    _validate_group_members(tests, groups, group_sources)
    return TestCatalog(path=None, tests=tests, groups=groups)


def _expand_testlist(path: Path, root: Path, stack: list[Path]) -> tuple[dict, dict, dict]:
    """Load one testlist file and recursively expand its includes, detecting cycles."""
    resolved = path.resolve()
    for seen in stack:
        if seen.resolve() == resolved:
            cycle = " -> ".join(p.name for p in stack + [path])
            raise ConfigError(f"testlist include cycle: {cycle}")
    if not path.is_file():
        chain = " -> ".join(p.name for p in stack + [path])
        raise ConfigError(f"missing testlist include: {path} (include chain: {chain})")
    return _merge_testlist_data(load_toml(path), path, path.parent, root, stack + [path])


def _merge_testlist_data(
    data: dict[str, Any],
    source: Path,
    base_dir: Path,
    root: Path,
    stack: list[Path],
    *,
    validate_testlist_keys: bool = True,
) -> tuple[dict, dict, dict]:
    """Merge included testlists first, then this file's own tests/groups.

    Include paths are resolved relative to the including file (``base_dir``); duplicate test or
    group names after expansion are validation errors. The third returned dict maps each group
    to the file that declared it, so cross-reference errors name the file to edit.
    """
    tests: dict[str, TestEntry] = {}
    groups: dict[str, list[str]] = {}
    group_sources: dict[str, Path] = {}
    if validate_testlist_keys:
        validate_allowed_keys(data, TESTLIST_KEYS, str(source))

    for include in as_str_list(data.get("includes"), f"{source}: includes"):
        inc = Path(include).expanduser()
        inc_path = inc if inc.is_absolute() else base_dir / inc
        try:
            inc_path.resolve().relative_to(root.resolve())
        except ValueError:
            raise ConfigError(f"{source}: include `{include}` resolves outside the repository root")
        inc_tests, inc_groups, inc_sources = _expand_testlist(inc_path, root, stack)
        for name, test in inc_tests.items():
            if name in tests:
                raise ConfigError(f"{source}: duplicate test `{name}` after include expansion")
            tests[name] = test
        for name, members in inc_groups.items():
            if name in groups:
                raise ConfigError(f"{source}: duplicate group `{name}` after include expansion")
            groups[name] = members
            group_sources[name] = inc_sources.get(name, inc_path)

    for entry in data.get("tests", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: each [[tests]] entry must be a table")
        validate_allowed_keys(entry, TEST_KEYS, f"{source} [[tests]]")
        validate_placeholders_in_value(entry, f"{source} [[tests]]")
        test = _test_from_dict(entry, source)
        if test.name in tests:
            raise ConfigError(f"{source}: duplicate test `{test.name}`")
        tests[test.name] = test

    for entry in data.get("groups", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: each [[groups]] entry must be a table")
        validate_allowed_keys(entry, GROUP_KEYS, f"{source} [[groups]]")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"{source}: group entry missing required string `name`")
        if name in groups:
            raise ConfigError(f"{source}: duplicate group `{name}`")
        members = as_str_list(entry.get("tests"), f"{name}.tests")
        expected = as_int(entry.get("expected_count"), f"{name}.expected_count")
        if expected is not None and expected != len(members):
            raise ConfigError(
                f"{source}: group `{name}` lists {len(members)} tests but "
                f"expected_count is {expected}; update the group or the count"
            )
        groups[name] = members
        group_sources[name] = source

    return tests, groups, group_sources


def flow_stages(flow: Flow) -> dict[str, Any]:
    stages = flow.raw.get("native", {}).get("stages", {})
    if not isinstance(stages, dict):
        raise ConfigError(f"{flow.path}: [native.stages] must be a table")
    return stages
