# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Command-line orchestration for the native DV runner."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from re import compile
from typing import Any

from .compat import UTC
from .config import (
    CANONICAL_STAGES,
    OverlayFrameworkMismatch,
    activate_adopter_overlay_env,
    as_str_list,
    cocotb_cfg,
    coverage_cfg,
    default_target_name,
    flow_stages,
    load_executors,
    load_sim_cfg,
    load_simulators,
    load_test_catalog,
    merge_simulator_defaults,
    parse_walltime_sec,
    resolved_target_name,
    selected_target,
    target_names,
    targeted_sim_cfg,
    validate_native_config_shape,
    validate_run_mode_request,
)
from .coverage import CoverageError, artifact_ready, json_text, load_manifest, write_json_text
from .coverage_closure import (
    coverage_fail_under,
    coverage_merged_name,
    coverage_parser_name,
    coverage_run_paths,
    grade_coverage_run,
    parse_coverage_run,
)
from .coverage_combine import plan_combine
from .coverage_policy import (
    CoveragePolicy,
    load_coverage_policy,
    native_policy_manifest,
)
from .duts import (
    ConfigView,
    discover_formal_views,
    list_dut_names,
    load_duts,
    load_formal_views,
    resolve_dut,
    unavailable_sim_views,
)
from .executors import (
    ClusterError,
    build_executor,
    dispatch_blocker,
    executor_builds,
    executor_driver,
    executor_limits,
)
from .executors.base import (
    BUILD_ROLE,
    Executor,
    JobHandle,
    JobObservation,
    JobState,
    LeafTask,
    ResourceRequest,
    error_result,
    resolve_resources,
    task_identifier,
)
from .executors.manifest import (
    attempt_args,
    execute_attempt,
    manifest_path,
    manifest_payload,
    repo_identity,
    write_manifest,
)
from .junit import materialize_interruption_junit, materialize_stage_junit
from .logparse import validate_parser_extensions, validate_parser_registry
from .models import ConfigError, Flow, StageResult, TestCatalog
from .paths import configs_root, dut_runs_root, repo_path, repo_rel, repo_root
from .results import (
    aggregate_status,
    coverage_summary,
    exit_code_for_status,
    git_provenance,
    incomplete_run_note,
    regression_payload,
    result_payload,
    rollup_payload,
    run_is_complete,
    tool_versions,
    write_result,
)
from .site import (
    SiteLayer,
    ToolLaunch,
    launch_env,
    load_site_layer,
    locate_tool,
    merged_executors,
    merged_simulators,
    site_summary,
    tool_launch,
    tool_source,
    validate_site_dut_tools,
    validate_site_duts,
)
from .stages import (
    cocotb_python_paths,
    item_artifact_dir,
    request_stage_cancellation,
    reset_stage_cancellation,
    resolve_coverage_policy,
    run_stage,
    seed_for_item,
)
from .ui import Console
from .waves import (
    WAVE_DEFAULT,
    find_failure_time_ps,
    parse_time_ps,
    require_verdi_home,
    resolve_wave_format,
    waves_on_fail_requested,
)

REGRESSION_SEED_MAX = 2_147_483_647
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX_EXCLUSIVE = (3, 14)
# The distributions the locked `dv` group provides; the doctor reports one row per entry.
DOCTOR_DISTRIBUTIONS = ("cocotb", "pyuvm", "cocotbext-axi", "cocotbext-jtag")
# Registry tool name -> version-query argument; the doctor reports the first output line.
_DOCTOR_VERSION_ARGS = {
    "verilator": ["--version"],
    "vcs": ["-ID"],
    "xcelium": ["-version"],
    "sby": ["--version"],
}
# A release number as the tool registry's `min_version` and a tool's version line spell it.
_RELEASE_NUMBER_RE = compile(r"\d+(?:\.\d+)+")
_COVERAGE_STAGES = {"cov_merge", "cov_report"}
_WAIVE_REGRADEABLE_BUCKETS = {"coverage_threshold", "config_error"}
# --doctor import probe: modules per child interpreter, and the seconds each child
# has before it is killed. OCAH_DOCTOR_PROBE_TIMEOUT replaces the default budget.
DOCTOR_PROBE_BATCH_SIZE = 20
DOCTOR_PROBE_TIMEOUT_DEFAULT = 120.0
DOCTOR_PROBE_TIMEOUT_ENV = os.environ.get("OCAH_DOCTOR_PROBE_TIMEOUT", "")


class RunInterrupted(BaseException):
    """Raised by the main-thread signal handler after recording the signal."""

    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(signal.Signals(signum).name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        usage=(
            "%(prog)s --dut NAME [--framework NAME] [--items ITEM ...] [options]\n"
            "       %(prog)s --list | --validate-configs | --doctor [options]"
        ),
        description=textwrap.dedent(
            """\
            Native OSS DV/FV launcher.

            Select a DUT (--dut) and, when it implements more than one test framework,
            a framework (--framework); pick tests or groups from its testlist
            (--items/--tag); run them on a simulator (--tool). Start with --list to see
            what exists and --doctor to check this machine can run it.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:

              Discover what exists:
                python3 tools/dv/run_dv.py --list                    # DUTs, frameworks, tools
                python3 tools/dv/run_dv.py --dut dtp --list          # one DUT's tests and groups
                python3 tools/dv/run_dv.py --doctor --dut dtp        # can this machine run it?
                python3 tools/dv/run_dv.py --validate-configs        # are all configs consistent?

              Run tests (the DUT's default framework and tool):
                python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test
                python3 tools/dv/run_dv.py --dut smc --items smoke --tool vcs
                python3 tools/dv/run_dv.py --dut smc --items smoke --regress --reseed 10
                python3 tools/dv/run_dv.py --dut smc --build-only --dry-run

              Pick a framework (same scenario names, different implementation):
                python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_sanity_test
                python3 tools/dv/run_dv.py --dut dtp --framework uvm --items smoke
                python3 tools/dv/run_dv.py --dut sep --framework uvm --items smoke --skip-unimplemented

              Debug a failure:
                python3 tools/dv/run_dv.py --dut smc --items smoke --waves-on-fail fst
                python3 tools/dv/run_dv.py --dut smc --items smc_cold_reset_test --stage sim --seed 7

              Feed CI or the dashboard:
                python3 tools/dv/run_dv.py --list --json             # (DUT, framework) matrix
                python3 tools/dv/run_dv.py --dut dtp --list --json   # scenario binding matrix
            """
        ),
    )

    common = parser.add_argument_group("Common Selection")
    common.add_argument(
        "--dut",
        metavar="NAME",
        help="DUT name from hw/common/dv/configs/duts.toml or the hw/** convention",
    )
    common.add_argument(
        "--mode",
        choices=["sim", "formal"],
        default="sim",
        help="Verification mode: simulation (default) or formal",
    )
    common.add_argument(
        "--framework",
        metavar="NAME",
        help="Test framework (e.g. cocotb, uvm); defaults to the DUT's default_framework",
    )
    common.add_argument(
        "--items",
        nargs="+",
        metavar="ITEM",
        help="Test or group names from the DUT's testlist (default: the `smoke` group)",
    )
    common.add_argument(
        "--tag",
        action="append",
        metavar="TAG",
        help="Select tests carrying any tag; filters --items if both are given",
    )
    common.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Keep duplicate items when selected groups overlap",
    )
    common.add_argument(
        "--skip-unimplemented",
        action="store_true",
        help=(
            "Skip group/tag-selected scenarios whose binding map has no entry for the selected "
            "framework (default: error). Scenarios declaring the framework `false` skip without "
            "this flag; an explicitly named --items test errors either way"
        ),
    )
    common.add_argument(
        "--tool",
        metavar="TOOL",
        help="Simulator from simulators.toml (verilator, vcs, xcelium); defaults to the framework's default tool",
    )
    common.add_argument(
        "--run-mode",
        metavar="NAME",
        help="Run mode from the DUT sim config [run_modes.<name>] (default: the test's first run mode)",
    )
    common.add_argument(
        "--target",
        metavar="NAME",
        help=(
            "Build target from the DUT sim config [targets.<name>]; "
            "overrides every selected test's target (default: each test's own target)"
        ),
    )
    common.add_argument(
        "--overlay",
        metavar="PATH",
        help=(
            "Adopter overlay config applied append-only on top of the merged DUT view "
            "(extra build sources/incdirs/source_lists, target defines/flags, [sim].args, "
            "[env]); "
            "also read from OCAH_DV_OVERLAY, never auto-activated"
        ),
    )

    actions = parser.add_argument_group("Actions And Introspection")
    actions.add_argument(
        "--list",
        action="store_true",
        help="List configured DUTs or selected DUT details",
    )
    actions.add_argument(
        "--json",
        action="store_true",
        help=(
            "With --list: emit machine-readable JSON — one entry per (DUT, framework) view "
            "globally, or the full scenario binding matrix with --dut"
        ),
    )
    actions.add_argument(
        "--validate-configs",
        action="store_true",
        help="Validate all native DUT configs and print a per-DUT summary",
    )
    actions.add_argument(
        "--doctor",
        action="store_true",
        help="Report tool availability and config sanity for a selected DUT/tool, or all tools",
    )
    actions.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected commands and artifacts without executing backend tools",
    )

    stages = parser.add_argument_group("Stage And Build Control")
    stages.add_argument(
        "--stage",
        action="append",
        metavar="NAME",
        help="Run one named stage (repeatable), e.g. --stage flist --stage hdl_compile; `--dut X --list` shows a DUT's stages",
    )
    stages.add_argument("--build-only", action="store_true", help="Run build stages only")
    stages.add_argument("--run-only", action="store_true", help="Run sim/regress stages only")
    stages.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a clean build, ignoring any cached build",
    )
    stages.add_argument(
        "--timeout",
        type=int,
        metavar="SEC",
        help="Tool invocation timeout; overrides configured timeout_sec values",
    )

    output = parser.add_argument_group("Output And UI")
    output.add_argument(
        "--run-dir",
        metavar="DIR",
        help="Run output directory (default: <dut-dv-root>/build/runs/<stamp>__<tool>__<label>)",
    )
    output.add_argument(
        "--result",
        metavar="PATH",
        help="Write an extra copy of the run-level result JSON here (primary stays <run-dir>/result.json)",
    )
    output.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the final result and essential artifacts",
    )
    output.add_argument(
        "--verbose",
        action="store_true",
        help="Stream backend stdout live instead of keeping it in logs",
    )
    output.add_argument(
        "--ui",
        choices=["auto", "pretty", "plain"],
        default="auto",
        help="Terminal output style",
    )

    parallel = parser.add_argument_group("Parallelism And Executor Metadata")
    parallel.add_argument(
        "--sim-jobs",
        dest="sim_jobs",
        type=int,
        default=1,
        metavar="N",
        help="Simulation/regression fan-out job count",
    )
    parallel.add_argument(
        "--build-jobs",
        type=int,
        metavar="N",
        help=(
            "Backend compile/build job count; uses --sim-jobs when omitted, capped at this "
            "host's CPU count on a cluster executor"
        ),
    )
    parallel.add_argument(
        "--executor",
        default=None,
        metavar="NAME",
        help="Executor from executors.toml (`local`, or a cluster entry the run may use)",
    )
    parallel.add_argument(
        "--builds",
        choices=["local", "scheduler"],
        default=None,
        help=(
            "Where a cluster executor runs the target builds: as scheduler jobs the leaves "
            "wait for, or in this process (the executor's `builds` key when omitted)"
        ),
    )
    parallel.add_argument("--queue", metavar="NAME", help="Executor queue/partition metadata")
    parallel.add_argument("--cores", type=int, metavar="N", help="Executor CPU-core request")
    parallel.add_argument("--mem-mb", type=int, metavar="MB", help="Executor memory request")
    parallel.add_argument("--walltime", metavar="TIME", help="Executor walltime request")

    regression = parser.add_argument_group("Regression And Randomization")
    regression.add_argument(
        "--regress",
        action="store_true",
        help="Run selected items through the local regression scheduler",
    )
    regression.add_argument(
        "--seed",
        type=int,
        metavar="N",
        help="Single-simulation seed override (integer; rejected in regression mode — use --reseed there)",
    )
    regression.add_argument(
        "--reseed",
        type=int,
        metavar="N",
        help="Run each selected regression test with N random seeds",
    )
    regression.add_argument(
        "--retry",
        type=int,
        default=0,
        metavar="N",
        help="Retry each non-passing regression leaf up to N times",
    )
    regression.add_argument(
        "--max-failures",
        type=int,
        metavar="N",
        help="Stop launching new regression leaves after N final failures",
    )

    waves = parser.add_argument_group("Wave Debug")
    waves.add_argument(
        "--waves",
        nargs="?",
        const=WAVE_DEFAULT,
        metavar="FMT",
        help="Enable waves; FMT defaults to the tool's native format (fst/vpd/shm)",
    )
    waves.add_argument(
        "--waves-on-fail",
        nargs="?",
        const=WAVE_DEFAULT,
        metavar="FMT",
        help="Rerun non-passing leaves with waves enabled",
    )
    waves.add_argument(
        "--wave-start",
        metavar="TIME",
        help="Start waveform dumping at this simulation time (fs|ps|ns|us|ms|s)",
    )
    waves.add_argument(
        "--wave-end",
        metavar="TIME",
        help="Stop waveform dumping at this simulation time (fs|ps|ns|us|ms|s)",
    )
    waves.add_argument(
        "--wave-window",
        metavar="TIME",
        help="Dump this interval before the parsed failure time on --waves-on-fail reruns",
    )
    waves.add_argument(
        "--wave-margin",
        metavar="TIME",
        help="Dump this interval after the parsed failure time when --wave-window is used",
    )
    waves.add_argument(
        "--wave-retention",
        choices=["all", "failed", "none"],
        help="Wave artifact retention policy",
    )

    coverage = parser.add_argument_group("Coverage")
    coverage.add_argument(
        "--cov",
        action="store_true",
        help="Enable simulator-native coverage and append the cov_merge/cov_report stages",
    )
    coverage.add_argument(
        "--fail-under",
        type=float,
        metavar="PCT",
        help="Coverage report threshold override",
    )
    coverage.add_argument(
        "--cov-combine",
        nargs="+",
        metavar="RUN_DIR",
        help=(
            "Combine the coverage of the finished runs at RUN_DIR... into one new graded run "
            "directory (--run-dir names it); the runs must share the DUT, the tool and the "
            "commit, and no simulator runs"
        ),
    )
    coverage.add_argument(
        "--waive",
        nargs="?",
        const="",
        default=None,
        metavar="FILE",
        help=(
            "Re-grade the finished run in --run-dir against the DUT's coverage policy, or "
            "against FILE (a relative FILE resolves against the repository root); no simulator "
            "or report tool runs"
        ),
    )

    backend = parser.add_argument_group("Backend Pass-Through Args")
    backend.add_argument(
        "--define",
        action="append",
        metavar="NAME[=VALUE]",
        help="Extra Verilog define for compile/elaboration",
    )
    backend.add_argument(
        "--comp-arg",
        action="append",
        metavar="ARG",
        help="Extra HDL compile/elaborate backend argument",
    )
    backend.add_argument(
        "--c-arg",
        action="append",
        metavar="ARG",
        help="Extra C/firmware/DPI build argument for the c_compile stage",
    )
    backend.add_argument(
        "--sim-arg",
        action="append",
        metavar="ARG",
        help="Extra simulator-runtime argument",
    )
    backend.add_argument(
        "--plusarg",
        action="append",
        metavar="ARG",
        help="Extra simulator plusarg",
    )

    formal = parser.add_argument_group("Formal Mode")
    formal.add_argument(
        "--proof-depth",
        type=int,
        metavar="N",
        help="Formal bounded proof depth override",
    )
    formal.add_argument(
        "--formal-arg",
        action="append",
        metavar="ARG",
        help="Extra formal tool argument",
    )
    formal.add_argument("--app", metavar="NAME", help="Formal app override")
    return parser.parse_args(argv)


def _flag_was_set(args: argparse.Namespace, name: str) -> bool:
    value = getattr(args, name)
    if isinstance(value, bool):
        return value
    if isinstance(value, list):
        return bool(value)
    if value == 0:
        return False
    return value is not None


_SIM_ONLY_FLAGS = {
    "seed": "--seed",
    "reseed": "--reseed",
    "retry": "--retry",
    "max_failures": "--max-failures",
    "run_mode": "--run-mode",
    "target": "--target",
    "waves": "--waves",
    "waves_on_fail": "--waves-on-fail",
    "wave_start": "--wave-start",
    "wave_end": "--wave-end",
    "wave_window": "--wave-window",
    "wave_margin": "--wave-margin",
    "wave_retention": "--wave-retention",
    "cov": "--cov",
    "fail_under": "--fail-under",
    "waive": "--waive",
    "cov_combine": "--cov-combine",
    "rebuild": "--rebuild",
    "define": "--define",
    "comp_arg": "--comp-arg",
    "c_arg": "--c-arg",
    "sim_arg": "--sim-arg",
    "plusarg": "--plusarg",
    "regress": "--regress",
}
_FORMAL_ONLY_FLAGS = {
    "proof_depth": "--proof-depth",
    "formal_arg": "--formal-arg",
    "app": "--app",
}
# Options a --waive re-grade accepts besides --dut, --run-dir, --tool, --framework,
# --overlay, --verbose and --quiet.
_WAIVE_COMPANIONS = {"fail_under", "waive"}
_WAIVE_SELECTION_FLAGS = {
    "stage": "--stage",
    "items": "--items",
    "tag": "--tag",
    "build_only": "--build-only",
    "run_only": "--run-only",
    "dry_run": "--dry-run",
}


def validate_mode_options(args: argparse.Namespace) -> None:
    if args.mode == "formal":
        for attr, flag in _SIM_ONLY_FLAGS.items():
            if _flag_was_set(args, attr):
                raise ConfigError(f"{flag} is simulation-only; selected mode is formal")
    else:
        for attr, flag in _FORMAL_ONLY_FLAGS.items():
            if _flag_was_set(args, attr):
                raise ConfigError(f"{flag} is formal-only; selected mode is sim")
    if args.sim_jobs < 1:
        raise ConfigError("--sim-jobs must be >= 1")
    if args.build_jobs is not None and args.build_jobs < 1:
        raise ConfigError("--build-jobs must be >= 1")
    if args.fail_under is not None and not 0.0 <= args.fail_under <= 100.0:
        raise ConfigError("--fail-under must be between 0 and 100")
    if args.reseed is not None and args.reseed < 1:
        raise ConfigError("--reseed must be >= 1")
    if args.retry is not None and args.retry < 0:
        raise ConfigError("--retry must be >= 0")
    if args.max_failures is not None and args.max_failures < 0:
        raise ConfigError("--max-failures must be >= 0")
    wave_range_requested = any(
        getattr(args, key, None)
        for key in ("wave_start", "wave_end", "wave_window", "wave_margin", "wave_retention")
    )
    if wave_range_requested and not args.waves and not args.waves_on_fail:
        raise ConfigError("wave range/retention options require --waves or --waves-on-fail")
    if args.wave_end and not args.wave_start and not args.wave_window:
        raise ConfigError("--wave-end requires --wave-start or --wave-window")
    if args.wave_margin and not args.wave_window:
        raise ConfigError("--wave-margin requires --wave-window")
    for attr, flag in (
        ("wave_start", "--wave-start"),
        ("wave_end", "--wave-end"),
        ("wave_window", "--wave-window"),
        ("wave_margin", "--wave-margin"),
    ):
        parse_time_ps(getattr(args, attr, None), flag)


def validate_duplicate_purpose_keys(
    flow: Flow, sim_cfg: dict[str, Any], simulators: dict[str, Any]
) -> None:
    errors: list[str] = []
    defaults = sim_cfg.get("defaults", {})
    if isinstance(defaults, dict) and "tool" in defaults:
        errors.append("[defaults].tool duplicates top-level default_tool; use default_tool")

    run_modes = sim_cfg.get("run_modes", {})
    if isinstance(run_modes, dict):
        for name, mode in sorted(run_modes.items()):
            if isinstance(mode, dict) and "tags" in mode:
                errors.append(f"[run_modes.{name}].tags duplicates testlist tags; remove it")

    build_options = (
        sim_cfg.get("build", {}).get("options", {})
        if isinstance(sim_cfg.get("build"), dict)
        else {}
    )
    if isinstance(build_options, dict):
        for key in ("ccache", "output_split"):
            if key in build_options:
                errors.append(
                    f"[build.options].{key} is Verilator-specific; use [build.verilator].{key}"
                )

    deprecated_target_keys = {
        "verilator_flags": "tools.verilator.flags",
        "xcelium_flags": "tools.xcelium.flags",
        "vcs_flags": "tools.vcs.flags",
    }
    for section_name in ("target_defaults", "targets"):
        section = sim_cfg.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for target_name, target in sorted(section.items()):
            if not isinstance(target, dict):
                continue
            for old_key, new_key in deprecated_target_keys.items():
                if old_key in target:
                    errors.append(
                        f"[{section_name}.{target_name}].{old_key} is deprecated; use {new_key}"
                    )

    for section, default_key in (
        ("build", "build_defaults"),
        ("coverage", "coverage_defaults"),
    ):
        section_cfg = sim_cfg.get(section, {})
        if not isinstance(section_cfg, dict):
            continue
        for tool in flow.tools:
            tool_cfg = section_cfg.get(tool, {})
            sim_tool = simulators.get(tool, {})
            if not isinstance(tool_cfg, dict) or not isinstance(sim_tool, dict):
                continue
            if section == "build" and "extra_build_args" in tool_cfg:
                errors.append(f"[build.{tool}].extra_build_args is deprecated; use extra_args")
            if section == "coverage":
                for old_key in (
                    f"{tool}_build_args",
                    f"{tool}_compile_args",
                    f"{tool}_sim_args",
                    f"{tool}_test_args",
                    "verilator_build_args",
                    "xcelium_build_args",
                    "xcelium_test_args",
                    "vcs_compile_args",
                    "vcs_sim_args",
                ):
                    if old_key in tool_cfg:
                        errors.append(
                            f"[coverage.{tool}].{old_key} is deprecated; use generic build_args/compile_args/sim_args/test_args"
                        )
            defaults_for_tool = sim_tool.get(default_key, {})
            if not isinstance(defaults_for_tool, dict):
                continue
            for key, value in sorted(tool_cfg.items()):
                if key in defaults_for_tool and value == defaults_for_tool[key]:
                    errors.append(
                        f"[{section}.{tool}].{key} duplicates simulators.toml "
                        f"[{tool}.{default_key}].{key}; omit it"
                    )

    if errors:
        joined = "; ".join(errors)
        raise ConfigError(f"{flow.path}: deprecated duplicate-purpose config: {joined}")


def coverage_policy_paths(flow: Flow, root: Path, sim_cfg: dict[str, Any]) -> list[Path]:
    """The coverage policy file of every tool the flow declares, where one exists."""

    coverage = sim_cfg.get("coverage", {})
    if not isinstance(coverage, dict):
        return []
    paths: list[Path] = []
    for tool in flow.tools:
        tool_coverage = coverage.get(tool, {})
        if not isinstance(tool_coverage, dict):
            continue
        configured = tool_coverage.get("policy_file")
        if isinstance(configured, str) and configured:
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute():
                repo_candidate = root / candidate
                candidate = (
                    repo_candidate if repo_candidate.is_file() else flow.path.parent / candidate
                )
        else:
            candidate = flow.path.parent / "cov" / "config" / tool / "coverage_policy.toml"
        if candidate.is_file():
            paths.append(candidate)
    return paths


def validate_coverage_policies(flow: Flow, root: Path, sim_cfg: dict[str, Any]) -> None:
    """Load every configured policy, raising on a schema error."""

    for path in coverage_policy_paths(flow, root, sim_cfg):
        load_coverage_policy(path, expected_dut=flow.name)


def validate_flow(
    flow: Flow,
    root: Path,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    executors: dict[str, Any] | None = None,
) -> None:
    """Validate one flow, raising ConfigError on the first problem."""

    if not (root / flow.root).exists():
        raise ConfigError(f"{flow.path}: root path does not exist: {flow.root}")
    for tool in flow.tools:
        if tool not in simulators:
            raise ConfigError(f"{flow.path}: tool `{tool}` missing from simulators.toml")
        capable = _tool_frameworks(simulators, tool)
        if flow.framework and capable and flow.framework not in capable:
            raise ConfigError(
                f"{flow.path}: tool `{tool}` does not support framework `{flow.framework}` "
                f"(supports: {', '.join(capable)})"
            )
    stages = flow_stages(flow)
    for stage_name, stage in stages.items():
        if stage_name not in CANONICAL_STAGES:
            raise ConfigError(f"{flow.path}: unsupported native stage `{stage_name}`")
        if not isinstance(stage, dict):
            raise ConfigError(f"{flow.path}: [native.stages.{stage_name}] must be a table")
        if not isinstance(stage.get("kind"), str):
            raise ConfigError(f"{flow.path}: native stage `{stage_name}` missing string `kind`")
    sim_cfg = load_sim_cfg(flow, root)
    validate_native_config_shape(flow, root)
    validate_coverage_policies(flow, root, sim_cfg)
    if executors is not None:
        scheduler = flow.raw.get("scheduler", {})
        if not isinstance(scheduler, dict):
            raise ConfigError(f"{flow.path}: [scheduler] must be a table")
        default_executor = str(scheduler.get("default_executor", "local"))
        allowed = as_str_list(scheduler.get("allowed"), "scheduler.allowed")
        for executor in [default_executor, *allowed]:
            if executor and executor not in executors:
                raise ConfigError(f"{flow.path}: executor `{executor}` missing from executors.toml")
    validate_duplicate_purpose_keys(flow, sim_cfg, simulators)
    merge_simulator_defaults(sim_cfg, simulators, flow.tools)
    load_test_catalog(flow, root)
    validate_parser_extensions(flow, simulators, policies)


@dataclass(frozen=True)
class Registries:
    """The tool, executor, and parser registries one command resolves against."""

    simulators: dict[str, Any]
    executors: dict[str, Any]
    policies: dict[str, Any]
    site: SiteLayer | None
    # Tools simulators.toml declares; the rest of `simulators` came from the site layer.
    checked_in_tools: frozenset[str]

    def tool_source(self, tool: str) -> str:
        return tool_source(self.site, tool, tool in self.checked_in_tools)

    def site_summary(self) -> str:
        return site_summary(self.site, self.checked_in_tools) if self.site is not None else ""


def load_registries(root: Path) -> Registries:
    """Load the registries and merge the active site layer over them.

    Every command resolves its registries here, so validation, --doctor, --dry-run, and the run
    path see one merged view, and no command reaches a tool table the others do not.
    """
    simulators = load_simulators(root)
    executors = load_executors(root)
    policies = validate_parser_registry(root)
    site = load_site_layer(root)
    merged = merged_simulators(simulators, site)
    if site is not None:
        validate_site_duts(site, list_dut_names(root))
        validate_site_dut_tools(site, merged)
    return Registries(
        simulators=merged,
        executors=merged_executors(executors, site),
        policies=policies,
        site=site,
        checked_in_tools=frozenset(simulators),
    )


def validate_all(root: Path) -> tuple[dict[str, Flow], Registries, dict[str, ConfigView]]:
    """Load and validate every selectable DUT and every available formal view.

    A simulation or formal view whose site-named file is absent stays unavailable and is not
    an error here; selecting its DUT in that mode is.
    """
    registries = load_registries(root)
    duts = load_duts(root, registries.site)
    for flow in duts.values():
        validate_flow(flow, root, registries.simulators, registries.policies, registries.executors)
    formal_views = load_formal_views(root, registries.site)
    for view in formal_views.values():
        if view.flow is not None:
            validate_flow(
                view.flow, root, registries.simulators, registries.policies, registries.executors
            )
    return duts, registries, formal_views


def adopter_overlay_path(args: Any) -> Path | None:
    """The adopter overlay selected by ``--overlay`` (wins) or ``OCAH_DV_OVERLAY``; else None.

    A relative path resolves against the invocation directory, like any other CLI path. The
    overlay is never inferred from the tree — only these two explicit channels activate it.
    """
    text = getattr(args, "overlay", None) or os.environ.get("OCAH_DV_OVERLAY", "").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def cmd_validate_configs(root: Path, overlay: Path | None = None) -> int:
    """Validate every config and print a per-DUT summary.

    Unlike the run path (which fails fast), this reports every DUT's status in one pass so a user
    sees all config problems at once instead of fixing them one re-run at a time. With an adopter
    overlay active, every framework view is validated WITH the overlay applied; views excluded by
    the overlay's `frameworks` guard fall back to their base validation and say so.
    """
    print(f"Validating configs in {repo_rel(root, configs_root(root))}")
    if overlay is not None:
        print(f"Adopter overlay: {repo_rel(root, overlay)}")
    print()

    # The registries are structural: per-flow validation cannot run without them, so a failure here
    # is reported on its own and stops the report.
    try:
        registries = load_registries(root)
    except ConfigError as exc:
        print(f"  registries       FAIL: {exc}")
        print("\nResult: registry error — fix it before flows can be validated")
        return 2
    simulators, executors, policies = (
        registries.simulators,
        registries.executors,
        registries.policies,
    )
    print("  simulators.toml  OK")
    print("  executors.toml   OK")
    print("  parsers.toml     OK")
    if registries.site is not None:
        print(f"  site layer       OK ({registries.site_summary()})")

    try:
        duts = load_duts(root, registries.site)
        absent_sim = unavailable_sim_views(root, registries.site)
    except ConfigError as exc:
        print(f"  DUT discovery    FAIL: {exc}")
        print("\nResult: could not load the DUT set")
        return 2

    try:
        formal_views = discover_formal_views(root, registries.site)
    except ConfigError as exc:
        print(f"  formal views     FAIL: {exc}")
        print("\nResult: could not discover the formal views")
        return 2

    failures = 0
    unavailable = 0
    rows = 0

    def check(label: str, name: str, mode: str, fw: str | None, base: Flow | None) -> None:
        nonlocal failures
        site = registries.site
        try:
            suffix = ""
            if overlay is not None:
                try:
                    view = resolve_dut(
                        root, name, mode=mode, framework=fw, adopter_overlay=overlay, site=site
                    )
                    suffix = " [+overlay]"
                except OverlayFrameworkMismatch:
                    view = base or resolve_dut(root, name, mode=mode, framework=fw, site=site)
                    suffix = " [overlay skipped: frameworks guard]"
            else:
                view = base or resolve_dut(root, name, mode=mode, framework=fw, site=site)
            validate_flow(view, root, simulators, policies, executors)
            print(f"  {label:<16} OK{suffix}")
        except ConfigError as exc:
            failures += 1
            print(f"  {label:<16} FAIL: {exc}")

    for name in sorted(set(duts) | set(absent_sim)):
        if name in absent_sim:
            # The checkout the site layer points into may be absent on this machine.
            rows += 1
            unavailable += 1
            print(f"  {name:<16} UNAVAILABLE: {absent_sim[name].reason}")
            continue
        flow = duts[name]
        # Validate every framework view a DUT implements, not only its default: the default row
        # keeps the bare DUT name; additional frameworks get their own `name (fw)` row.
        views: list[tuple[str, str | None]] = [(name, None)]
        views += [(f"{name} ({fw})", fw) for fw in flow.frameworks if fw != flow.framework]
        for label, fw in views:
            rows += 1
            check(label, name, "sim", fw, flow if fw is None else None)
    for name in sorted(formal_views):
        formal = formal_views[name]
        label = f"{name} (formal)"
        rows += 1
        if formal.available:
            check(label, name, "formal", None, None)
        elif formal.source == "site":
            # The companion checkout the site layer points into may be absent on this machine.
            unavailable += 1
            print(f"  {label:<16} UNAVAILABLE: {formal.reason}")
        else:
            failures += 1
            print(f"  {label:<16} FAIL: {formal.reason}")

    total = len(set(duts) | set(absent_sim))
    tail = f", {unavailable} unavailable" if unavailable else ""
    print(
        f"\nResult: {total} DUT(s), {rows} view(s): "
        f"{rows - failures - unavailable} OK, {failures} FAILED{tail}"
    )
    return 0 if failures == 0 else 2


def _version_text(parts: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in parts)


def _python_supported() -> tuple[bool, str]:
    version = sys.version_info[:3]
    min_ok = version >= (*SUPPORTED_PYTHON_MIN, 0)
    max_ok = version < (*SUPPORTED_PYTHON_MAX_EXCLUSIVE, 0)
    if min_ok and max_ok:
        return True, f"{version[0]}.{version[1]}.{version[2]}"
    supported = (
        f">={_version_text(SUPPORTED_PYTHON_MIN)},<{_version_text(SUPPORTED_PYTHON_MAX_EXCLUSIVE)}"
    )
    return (
        False,
        f"{version[0]}.{version[1]}.{version[2]} (supported range: {supported})",
    )


def _dist_version(dist_name: str) -> str | None:
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _print_doctor_row(name: str, status: str, detail: str) -> None:
    print(f"  {name:<24} {status:<8} {detail}")


def _path_in_sys_path(path: Path) -> bool:
    resolved = path.resolve()
    for entry in sys.path:
        try:
            if Path(entry or ".").resolve() == resolved:
                return True
        except OSError:
            continue
    return False


def _path_in_pythonpath(path: Path) -> bool:
    resolved = str(path.resolve())
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if str(Path(entry).resolve()) == resolved:
                return True
        except OSError:
            continue
    return False


_PROBE_SCRIPT = """\
import importlib, json, sys
# cocotb assigns simulation-time attributes before importing test modules
# (cocotb._init._setup_logging); mirror the one commonly touched at import
# scope so this bare-interpreter probe matches the run's import context.
try:
    import cocotb, logging
    cocotb.log = logging.getLogger("test")
except ImportError:
    pass
out = {}
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
        out[name] = [True, "import OK"]
    except Exception as exc:
        out[name] = [False, f"{type(exc).__name__}: {exc}"]
print(json.dumps(out))
"""


def doctor_probe_timeout() -> float:
    """Return the per-batch import-probe budget in seconds.

    `OCAH_DOCTOR_PROBE_TIMEOUT` must be a positive number when set; unset means the default.
    """
    raw = DOCTOR_PROBE_TIMEOUT_ENV.strip()
    if not raw:
        return DOCTOR_PROBE_TIMEOUT_DEFAULT
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise ConfigError(
            f"OCAH_DOCTOR_PROBE_TIMEOUT must be a number of seconds, got {raw!r}"
        ) from exc
    if seconds <= 0:
        raise ConfigError(f"OCAH_DOCTOR_PROBE_TIMEOUT must be positive, got {raw!r}")
    return seconds


def _probe_batch(
    python_paths: list[Path], batch: list[str], timeout: float
) -> dict[str, tuple[bool, str]] | None:
    """Import `batch` in one child interpreter; None means the child exceeded `timeout`."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths if str(path))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE_SCRIPT, *batch],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        return {name: (False, f"import probe failed to run: {exc}") for name in batch}
    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
        return {name: (bool(ok), str(detail)) for name, (ok, detail) in raw.items()}
    except (ValueError, IndexError):
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        tail = detail[-1] if detail else f"exit code {proc.returncode}"
        return {name: (False, f"import probe crashed: {tail}") for name in batch}


def _probe_imports(
    python_paths: list[Path],
    modules: list[str],
    *,
    timeout: float = DOCTOR_PROBE_TIMEOUT_DEFAULT,
    batch_size: int = DOCTOR_PROBE_BATCH_SIZE,
) -> dict[str, tuple[bool, str]]:
    """Import each module in child interpreters whose PYTHONPATH is exactly `python_paths`.

    Run stages rebuild PYTHONPATH for simulator children from the DUT config
    (:func:`runlib.stages.cocotb_python_paths`) instead of inheriting the launcher's ambient
    one, so probing through this process's ``sys.path`` reports failures runs never see.

    Modules are probed `batch_size` per child with `timeout` seconds each. A batch whose
    child exceeds the budget is retried once with twice the budget; only a batch that
    exceeds both is reported as failed, and only for its own modules.
    """
    if not modules:
        return {}
    results: dict[str, tuple[bool, str]] = {}
    for start in range(0, len(modules), batch_size):
        batch = modules[start : start + batch_size]
        outcome = _probe_batch(python_paths, batch, timeout)
        if outcome is None:
            outcome = _probe_batch(python_paths, batch, timeout * 2)
        if outcome is None:
            why = (
                f"import probe timed out twice ({timeout:g}s, then {timeout * 2:g}s) for a "
                f"batch of {len(batch)} modules; raise OCAH_DOCTOR_PROBE_TIMEOUT on a slow "
                "filesystem"
            )
            outcome = {name: (False, why) for name in batch}
        results.update(outcome)
    return results


def _tool_version_line(tool: str, executable: str, env: dict[str, str]) -> str:
    """The first line the located binary prints for its version query; "" when `tool` has none."""
    version_args = _DOCTOR_VERSION_ARGS.get(tool)
    if version_args is None:
        return ""
    try:
        proc = subprocess.run(
            [executable, *version_args],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = (proc.stdout or proc.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def _release_key(text: str) -> tuple[int, ...] | None:
    """The first dotted release number in `text` as integers, so `5.036` orders as (5, 36)."""
    match = _RELEASE_NUMBER_RE.search(text)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def _below_min_version(cfg: dict[str, Any], version_line: str) -> str:
    """The registry table's `min_version` when `version_line` reports an older release, else ""."""
    floor = cfg.get("min_version")
    if not isinstance(floor, str):
        return ""
    found = _release_key(version_line)
    required = _release_key(floor)
    if found is None or required is None or found >= required:
        return ""
    return floor


def _doctor_module_selection(
    catalog: TestCatalog, args: argparse.Namespace | None
) -> tuple[list[str], str]:
    """The tests whose modules the doctor probes, and the selection that named them.

    `--items` and `--tag` select as a run selects; without either, every test in the catalog is
    probed and the returned scope is empty.
    """
    items = list(getattr(args, "items", None) or [])
    tags = list(getattr(args, "tag", None) or [])
    if not items and not tags:
        return list(catalog.tests), ""
    names = expand_items(catalog, items, True) if items else list(catalog.tests)
    if tags:
        names = select_by_tags(catalog, names, tags)
        if not names:
            raise ConfigError(f"no tests match tag(s): {', '.join(tags)}")
    parts = [f"--items {' '.join(items)}"] if items else []
    parts.extend(f"--tag {tag}" for tag in tags)
    return names, " ".join(parts)


def _doctor_python_environment(
    root: Path, flow: Flow | None, selection: tuple[list[str], str] | None = None
) -> bool:
    """Check Python package/import readiness for OSS DV contributor flows.

    `selection` is the (test names, scope) pair :func:`_doctor_module_selection` returns for a
    `--items`/`--tag` selection; None probes every test in the catalog. Returns True when a
    selected flow cannot run in the current Python environment.
    """
    print("python/package:")
    failed = False

    py_ok, py_detail = _python_supported()
    _print_doctor_row("python", "OK" if py_ok else "FAIL", py_detail)
    if not py_ok:
        failed = True
        _print_doctor_row(
            "python fix",
            "INFO",
            "use Python 3.11, 3.12, or 3.13 for OSS DV; cocotb rejects Python >=3.14",
        )

    for dist_name in DOCTOR_DISTRIBUTIONS:
        version = _dist_version(dist_name)
        if version is None:
            failed = True
            _print_doctor_row(
                dist_name,
                "FAIL",
                "missing distribution "
                f"`{dist_name}`; launch via `python3 tools/dv/run_dv.py` (uv-managed) "
                "or run `uv sync --locked --group dv` at the repository root",
            )
        else:
            _print_doctor_row(dist_name, "OK", version)

    # The shared VIP (`ocah-dv`) needs no installed distribution: every run rebuilds
    # PYTHONPATH from the DUT config, which carries the in-repo VIP root.
    ocah_dv_version = _dist_version("ocah-dv")
    _print_doctor_row(
        "shared dv package",
        "OK" if ocah_dv_version else "WARN",
        ocah_dv_version
        or "distribution `ocah-dv` not installed; runs import the VIP from hw/common/dv/vip",
    )

    namespace_root = root / "build/dv/python"
    if namespace_root.is_dir():
        _print_doctor_row("namespace bridge", "OK", str(namespace_root))
    else:
        failed = True
        _print_doctor_row(
            "namespace bridge",
            "FAIL",
            "missing; launch via `python3 tools/dv/run_dv.py` (its bootstrap syncs the "
            "bridge) or run `python3 tools/dv/sync_python_namespace.py`",
        )

    if _path_in_sys_path(namespace_root) or _path_in_pythonpath(namespace_root):
        _print_doctor_row("namespace PYTHONPATH", "OK", str(namespace_root))
    else:
        failed = True
        _print_doctor_row(
            "namespace PYTHONPATH",
            "FAIL",
            "bridge root is not on PYTHONPATH; launch via `python3 tools/dv/run_dv.py` "
            "so its bootstrap exports it",
        )

    try:
        probe_timeout = doctor_probe_timeout()
    except ConfigError as exc:
        _print_doctor_row("probe budget", "FAIL", str(exc))
        print()
        return True

    # Probe the shared VIP from its in-repo root, the way DUT configs put it on PYTHONPATH.
    vip_root = root / "hw" / "common" / "dv" / "vip"
    vip_result = _probe_imports([vip_root, namespace_root], ["ocah_axi_vip"], timeout=probe_timeout)
    ok, detail = vip_result["ocah_axi_vip"]
    _print_doctor_row("import ocah_axi_vip", "OK" if ok else "FAIL", detail)
    failed |= not ok

    if flow is not None and flow.framework == "cocotb":
        # Import exactly what a run imports (each testlist `module`, cocotb's MODULE=) with
        # exactly the PYTHONPATH a run rebuilds, so pass/fail here predicts pass/fail there.
        run_paths = cocotb_python_paths(root, cocotb_cfg(flow, flow.raw))
        try:
            catalog = load_test_catalog(flow, root)
        except ConfigError as exc:
            _print_doctor_row("test modules", "FAIL", f"testlist did not load: {exc}")
            print()
            return True
        selected, scope = selection if selection is not None else (list(catalog.tests), "")
        modules = sorted({catalog.tests[name].module for name in selected} - {""})
        results = _probe_imports(run_paths, modules, timeout=probe_timeout)
        failures = [(name, results[name][1]) for name in modules if not results[name][0]]
        suffix = f" ({scope})" if scope else ""
        if not modules and scope:
            _print_doctor_row(
                "test modules",
                "WARN",
                f"the selection has no module for framework `{flow.framework}`{suffix}",
            )
        elif not modules:
            _print_doctor_row("test modules", "WARN", "testlist declares no tests")
        elif not failures:
            _print_doctor_row(
                "test modules",
                "OK",
                f"{len(modules)} modules import with the run PYTHONPATH{suffix}",
            )
        else:
            failed = True
            _print_doctor_row(
                "test modules",
                "FAIL",
                f"{len(failures)}/{len(modules)} modules failed to import{suffix}",
            )
            for name, why in failures[:5]:
                _print_doctor_row(f"  {name}", "FAIL", why)
            if len(failures) > 5:
                _print_doctor_row(
                    "  ...", "FAIL", f"{len(failures) - 5} more (same run PYTHONPATH)"
                )
            if not scope:
                _print_doctor_row(
                    "test modules fix",
                    "INFO",
                    "add --items <group or test> or --tag <tag> to probe only the modules "
                    "that selection imports",
                )
    elif flow is not None:
        _print_doctor_row(
            "DUT-local import", "SKIP", f"framework `{flow.framework}` has no DUT Python package"
        )
    else:
        _print_doctor_row(
            "DUT-local import", "SKIP", "select --dut <name> to check one DUT package"
        )

    print()
    return failed


def cmd_doctor(root: Path, args: argparse.Namespace) -> int:
    """Report whether the tools a run needs are actually installed on this machine.

    `--validate-configs` answers "is my config correct?"; `--doctor` answers "can I actually run it
    here?" — it confirms configs load, then probes tool binaries and license-env presence.
    """
    try:
        _duts, registries, _formal_views = validate_all(root)
        simulators, executors, policies = (
            registries.simulators,
            registries.executors,
            registries.policies,
        )
    except ConfigError as exc:
        print(f"configs : FAIL: {exc}")
        print("\nResult: fix config errors first (run --validate-configs for the full list)")
        return 2
    print("configs : OK")
    print(f"site    : {registries.site.label if registries.site is not None else 'none'}")

    flow: Flow | None = None
    if args.dut:
        try:
            flow = resolve_dut(
                root,
                args.dut,
                mode=args.mode,
                framework=args.framework,
                adopter_overlay=adopter_overlay_path(args),
                site=registries.site,
            )
            validate_flow(flow, root, simulators, policies, executors)
        except ConfigError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    required: str | None = None
    if flow is not None:
        tools = list(flow.tools)
        required = selected_tool(flow, args, simulators)
        scope = f"DUT `{flow.name}` (would run with: {required})"
    elif args.tool:
        tools = [args.tool]
        required = args.tool
        scope = f"tool `{args.tool}`"
    else:
        tools = sorted(simulators)
        scope = "all registered tools (survey)"

    selection: tuple[list[str], str] | None = None
    scoped = bool(getattr(args, "items", None) or getattr(args, "tag", None))
    if flow is not None and flow.framework == "cocotb" and scoped:
        try:
            selection = _doctor_module_selection(load_test_catalog(flow, root), args)
        except ConfigError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    print(f"checking: {scope}\n")
    python_failed = _doctor_python_environment(root, flow, selection)

    print(f"  {'tool':<10} {'binary':<12} {'status':<26} {'licenses':<14} source")
    missing_required = False
    required_too_old: tuple[str, str] | None = None
    for tool in tools:
        cfg = simulators.get(tool)
        if not isinstance(cfg, dict):
            print(f"  {tool:<10} {'?':<12} {'NOT IN REGISTRY':<26} -")
            if tool == required:
                missing_required = True
            continue
        launch = tool_launch(simulators, tool)
        hook_error = ""
        try:
            env = launch_env(launch)
        except ConfigError as exc:
            env = dict(os.environ)
            hook_error = str(exc)
        found = None if hook_error else locate_tool(launch, env)
        if hook_error:
            status = "setup_hook FAILED"
        elif launch.launcher:
            status = (
                f"launcher found: {found}" if found else f"launcher `{launch.executable}` MISSING"
            )
        else:
            status = f"found: {found}" if found else "MISSING from PATH"
        lic_env = as_str_list(cfg.get("license_env"), f"{tool}.license_env")
        if not lic_env:
            lic = "none needed"
        else:
            set_count = sum(1 for var in lic_env if env.get(var))
            lic = f"{set_count}/{len(lic_env)} env set"
        note = ""
        if not found:
            note = "  <- required" if tool == required else "  (optional)"
            if tool == required:
                missing_required = True
        print(
            f"  {tool:<10} {launch.binary:<12} {status:<26} {lic:<14} {registries.tool_source(tool)}{note}"
        )
        if hook_error:
            print(f"  {'':<10} {hook_error}")
        version = _tool_version_line(tool, found, env) if found and not launch.launcher else ""
        if version:
            floor = _below_min_version(cfg, version)
            print(
                f"  {'':<10} version: {version}{f'  <- below min_version {floor}' if floor else ''}"
            )
            if floor and tool == required:
                required_too_old = (version, floor)

    print()
    executor_rows, executor_missing = _doctor_executors(registries, flow, args)
    for row in executor_rows:
        print(row)
    print()
    if required is None:
        print("Result: survey only (no --dut/--tool selected); missing tools are informational")
        return 0
    if python_failed and flow is not None:
        print("Result: Python/package environment is NOT ready for this flow")
        return 2
    if missing_required:
        print(f"Result: required tool `{required}` is NOT available — this flow cannot run here")
        hint = license_hint(flow, simulators, required)
        if hint:
            print(f"Note: {hint}")
        return 2
    if required_too_old is not None:
        version, floor = required_too_old
        print(
            f"Result: required tool `{required}` is too old: {version}; "
            f"its registry table sets min_version {floor}"
        )
        return 2
    if executor_missing:
        name, binaries = executor_missing
        print(
            f"Result: executor `{name}` needs scheduler command(s) this machine lacks: "
            + ", ".join(binaries)
        )
        return 2
    print(f"Result: required tool `{required}` is available")
    return 0


def _doctor_executors(
    registries: Registries, flow: Flow | None, args: argparse.Namespace
) -> tuple[list[str], tuple[str, list[str]] | None]:
    """One row per registered executor; the selected one's missing binaries fail the doctor."""
    selected: str | None = None
    if flow is not None:
        try:
            selected = flow_executor_name(flow, args)
        except ConfigError:
            selected = None
    rows = [f"  {'executor':<10} {'driver':<8} status"]
    missing_selected: tuple[str, list[str]] | None = None
    for name in sorted(registries.executors):
        cfg = registries.executors[name]
        driver = executor_driver(cfg) or "-"
        if cfg.get("kind") == "local":
            status = "in-process"
        else:
            binaries = as_str_list(cfg.get("binaries"), f"{name}.binaries") or (
                [str(cfg["binary"])] if cfg.get("binary") else []
            )
            hook = cfg.get("setup_hook")
            launch = ToolLaunch(
                tool=name,
                binary=binaries[0] if binaries else name,
                setup_hook=Path(str(hook)) if hook else None,
            )
            try:
                env = launch_env(launch)
                hook_error = ""
            except ConfigError as exc:
                env = dict(os.environ)
                hook_error = str(exc)
            found = {binary: shutil.which(binary, path=env.get("PATH")) for binary in binaries}
            missing = [binary for binary, path in found.items() if not path]
            blocker = dispatch_blocker(name, cfg)
            parts = [
                "dispatch ready" if blocker is None else f"cannot dispatch ({blocker})",
                ", ".join(f"{binary} {'OK' if found[binary] else 'MISSING'}" for binary in binaries)
                or "no binaries declared",
            ]
            if hook_error:
                parts.append(f"setup_hook FAILED: {hook_error}")
            status = "; ".join(parts)
            if name == selected and (missing or hook_error):
                missing_selected = (name, missing or [str(hook)])
        note = "  <- selected" if name == selected else ""
        rows.append(f"  {name:<10} {driver:<8} {status}{note}")
    return rows, missing_selected


def _alias_of(name: str, flows: dict[str, Flow]) -> str | None:
    """The canonical DUT an `alias_of` name selects, or None when ``name`` is canonical.

    An alias resolves to its canonical :class:`Dut`, so the loaded name differs from the key.
    """
    flow = flows.get(name)
    return flow.name if flow is not None and flow.name != name else None


def _aliases_by_dut(flows: dict[str, Flow]) -> dict[str, list[str]]:
    """Canonical DUT name -> the sorted alias names that select it."""
    aliases: dict[str, list[str]] = {}
    for name in sorted(flows):
        canonical = _alias_of(name, flows)
        if canonical is not None:
            aliases.setdefault(canonical, []).append(name)
    return aliases


def _listed_formal_views(
    flows: dict[str, Flow], formal_views: dict[str, ConfigView]
) -> dict[str, ConfigView]:
    """The formal views to list: an alias's view is omitted when it is its canonical DUT's view."""
    listed: dict[str, ConfigView] = {}
    for name, view in formal_views.items():
        canonical = _alias_of(name, flows)
        canonical_view = formal_views.get(canonical) if canonical is not None else None
        if canonical_view is not None and canonical_view.path == view.path:
            continue
        listed[name] = view
    return listed


def list_flows(
    flows: dict[str, Flow],
    simulators: dict[str, Any],
    formal_views: dict[str, ConfigView] | None = None,
    unavailable_sim: dict[str, ConfigView] | None = None,
    root: Path | None = None,
    site: SiteLayer | None = None,
) -> None:
    """The DUT table: one row per simulation framework view, then the DUT's `fv` row.

    An alias gets a single row naming the DUT it selects. A simulation view whose site-named
    config is absent gets one row giving the reason. With ``root``, each framework row lists
    the tools of that framework's own view; without it, the tools of the DUT's default view.
    """
    BOLD = "\033[1m"
    NORMAL = "\033[0m"
    SELECT_BEGIN = BOLD
    SELECT_END = NORMAL

    # If using ANSI codes, these confuse fstring alignment, so must align manually
    ANSI_RE = compile(r"\033\[[0-9;]*m")

    def align(txt: str, width: int) -> str:
        return txt + " " * max(0, width - len(ANSI_RE.sub("", txt)))

    def format_selected_licensed(value: str, selected: bool, unlicensed: bool):
        return (
            (f"{SELECT_BEGIN}{value}{SELECT_END}" if selected else value)
            if unlicensed
            else (
                f"{SELECT_BEGIN}{value} (licensed){SELECT_END}"
                if selected
                else value + " (licensed)"
            )
        )

    widths: list[int] = [22, 4, 14, 46]

    print(
        f"{BOLD}{'NAME':<{widths[0]}} {'KIND':<{widths[1]}} {'FRAMEWORKS':<{widths[2]}} {'TOOLS':<{widths[3]}} {'DESCRIPTION'}{NORMAL}"
    )
    freesims = {name: not bool(attrs["license_env"]) for name, attrs in simulators.items()}
    freeframeworks: dict[str, bool] = {}
    frameworkTools: dict[str, list[str]] = {"": []}
    for sim, free in freesims.items():
        for framework in simulators[sim]["frameworks"]:
            freeframeworks[framework] = free or freeframeworks.get(framework, False)
            frameworkTools[framework] = frameworkTools.get(framework, []) + [sim]

    def tools_column(flow: Flow, framework: str) -> str:
        toolArr = list(set(flow.tools) & set(frameworkTools.get(framework, [])))
        defaultTool = (
            flow.default_tool
            if flow.default_tool in toolArr
            else toolArr[0]
            if len(toolArr)
            else ""
        )
        toolsArr = [
            format_selected_licensed(tool, tool == defaultTool, freesims[tool])
            for tool in sorted(
                toolArr, key=lambda x: (0, 0) if x == flow.default_tool else (1, str.lower(x))
            )
        ] or ["-"]
        return "/".join(toolsArr)

    def row(name: str, kind: str, label: str, tools: str, description: str) -> None:
        print(
            f"{name:<{widths[0]}} {kind:<{widths[1]}} {align(label, widths[2])} {align(tools, widths[3])} {description}"
        )

    formal_views = _listed_formal_views(flows, formal_views or {})
    unavailable_sim = unavailable_sim or {}
    for name in sorted(set(flows) | set(formal_views) | set(unavailable_sim)):
        flow = flows.get(name)
        canonical = _alias_of(name, flows)
        if canonical is not None:
            print(f"{name:<{widths[0]}} alias of {canonical}")
        elif name in unavailable_sim:
            row(name, "-", "-", "-", f"unavailable: {unavailable_sim[name].reason}")
        elif flow is not None:
            spill = False
            frameworks = {
                framework: format_selected_licensed(
                    framework,
                    (flow.framework and framework == flow.framework)
                    or (not flow.framework and framework == flow.default_framework),
                    freeframeworks[framework],
                )
                for framework in sorted(
                    flow.frameworks,
                    key=lambda x: (0, 0) if x == flow.default_framework else (1, str.lower(x)),
                )
            } or {"": "-"}
            for framework, label in frameworks.items():
                view = (
                    resolve_dut(root, name, framework=framework, site=site)
                    if root is not None and framework and framework != flow.framework
                    else flow
                )
                row(
                    flow.name if not spill else "",
                    flow.kind if not spill else " " + chr(8627),
                    label,
                    tools_column(view, framework),
                    flow.description if not spill else "",
                )
                spill = True
        view = formal_views.get(name)
        if view is None:
            continue
        if view.flow is None:
            row(name, "fv", "formal", "-", f"unavailable: {view.reason}")
            continue
        row(
            name,
            view.flow.kind,
            format_selected_licensed("formal", True, freeframeworks.get("formal", False)),
            tools_column(view.flow, "formal"),
            view.flow.description,
        )


def _binding_matrix(flow: Flow, catalog: TestCatalog) -> dict[str, dict[str, int]]:
    """Per framework: scenarios bound, declared `false`, and lacking any entry.

    The three counts sum to the catalog size for every framework the DUT implements.
    """
    frameworks = flow.frameworks or ([flow.framework] if flow.framework else [])
    matrix: dict[str, dict[str, int]] = {}
    for fw in frameworks:
        implemented = sum(1 for test in catalog.tests.values() if fw in test.bindings)
        excluded = sum(1 for test in catalog.tests.values() if fw in test.excluded)
        matrix[fw] = {
            "implemented": implemented,
            "excluded": excluded,
            "missing": len(catalog.tests) - implemented - excluded,
        }
    return matrix


def _implemented_counts(flow: Flow, catalog: TestCatalog) -> dict[str, int]:
    """Scenario count per implemented framework — the binding-matrix summary."""
    return {fw: row["implemented"] for fw, row in _binding_matrix(flow, catalog).items()}


def _implemented_summary(flow: Flow, catalog: TestCatalog) -> str:
    """One line per framework, e.g. `uvm 151/153 (2 excluded)`; zero counts stay silent."""
    parts = []
    for fw, row in _binding_matrix(flow, catalog).items():
        detail = ", ".join(f"{row[key]} {key}" for key in ("excluded", "missing") if row[key])
        parts.append(
            f"{fw} {row['implemented']}/{len(catalog.tests)}" + (f" ({detail})" if detail else "")
        )
    return ", ".join(parts)


def list_flow_detail(flow: Flow, root: Path) -> None:
    catalog = load_test_catalog(flow, root)
    multi_framework = bool(flow.frameworks) and flow.frameworks != [flow.framework]
    print(f"name       : {flow.name}")
    print(f"kind       : {flow.kind}")
    print(f"framework  : {flow.framework}")
    if multi_framework:
        print(f"frameworks : {', '.join(flow.frameworks)} (default: {flow.default_framework})")
        print("implemented: " + _implemented_summary(flow, catalog))
    print(f"root       : {flow.root}")
    print(f"tools      : {', '.join(flow.tools)}")
    print(f"default    : {flow.default_tool}")
    print(f"license    : {flow.license}")
    print(f"runnability: {flow.runnability}")
    print(f"stages     : {', '.join(flow_stages(flow))}")
    if catalog.tests:
        # Scenarios implemented beyond the default framework are marked (+fw) and frameworks
        # declared `false` are marked (-fw): the compact human view of the binding matrix
        # (--json carries the full per-scenario map).
        default = flow.default_framework or flow.framework
        names = []
        for name in sorted(catalog.tests):
            test = catalog.tests[name]
            marks = [f"+{fw}" for fw in sorted(set(test.bindings) - {default})]
            marks += [f"-{fw}" for fw in sorted(test.excluded)]
            names.append(name + (f" ({','.join(marks)})" if marks else ""))
        print("tests      : " + ", ".join(names))
    if catalog.groups:
        print(
            "groups     : "
            + ", ".join(
                f"{name}={','.join(items)}" for name, items in sorted(catalog.groups.items())
            )
        )


def _flow_view_dict(flow: Flow) -> dict[str, Any]:
    return {
        "name": flow.name,
        "kind": flow.kind,
        "mode": "formal" if flow.kind == "fv" else "sim",
        "available": True,
        "framework": flow.framework,
        "default": flow.framework == flow.default_framework,
        "frameworks": list(flow.frameworks),
        "default_framework": flow.default_framework,
        "tools": list(flow.tools),
        "default_tool": flow.default_tool,
        "visibility": flow.visibility,
        "runnability": flow.runnability,
        "license": flow.license,
        "root": flow.root,
        "description": flow.description,
    }


def list_flows_json(
    root: Path,
    flows: dict[str, Flow],
    formal_views: dict[str, ConfigView] | None = None,
    unavailable_sim: dict[str, ConfigView] | None = None,
    site: SiteLayer | None = None,
) -> None:
    """Machine-readable enumeration: one entry per (DUT, framework) view plus one per formal view.

    CI matrices consume this instead of hardcoding DUT names — e.g. a licensed UVM job selects
    `.duts[] | select(.framework == "uvm")` and gets the per-view tool set and license need;
    a formal job selects `.duts[] | select(.mode == "formal" and .available)`.
    An alias adds no entry of its own, so a matrix never runs one DUT twice; every entry
    lists the names that select the same DUT under `aliases`. A simulation view whose
    site-named config is absent is one entry with `available` false; its kind and frameworks
    live in the absent file, so it carries neither.
    """
    views: list[dict[str, Any]] = []
    for name in sorted(flows):
        if _alias_of(name, flows) is not None:
            continue
        flow = flows[name]
        views.append(_flow_view_dict(flow))
        for fw in flow.frameworks:
            if fw != flow.framework:
                views.append(_flow_view_dict(resolve_dut(root, name, framework=fw, site=site)))
    for name, view in sorted((unavailable_sim or {}).items()):
        views.append(
            {
                "name": name,
                "mode": "sim",
                "available": False,
                "path": repo_rel(root, view.path),
                "reason": view.reason,
            }
        )
    for name, view in sorted(_listed_formal_views(flows, formal_views or {}).items()):
        if view.flow is not None:
            views.append({**_flow_view_dict(view.flow), "name": name})
        else:
            views.append(
                {
                    "name": name,
                    "kind": "fv",
                    "mode": "formal",
                    "available": False,
                    "framework": "formal",
                    "path": repo_rel(root, view.path),
                    "reason": view.reason,
                }
            )
    aliases = _aliases_by_dut(flows)
    for entry in views:
        entry["aliases"] = aliases.get(entry["name"], [])
    print(json.dumps({"schema_version": 1, "duts": views}, indent=2))


def list_flow_detail_json(flow: Flow, root: Path) -> None:
    """Machine-readable DUT detail: the selected view plus the full scenario binding matrix."""
    catalog = load_test_catalog(flow, root)
    payload = {"schema_version": 1, **_flow_view_dict(flow)}
    payload["stages"] = list(flow_stages(flow))
    payload["total_scenarios"] = len(catalog.tests)
    payload["implemented"] = _implemented_counts(flow, catalog)
    payload["binding_matrix"] = _binding_matrix(flow, catalog)
    payload["tests"] = {
        name: {
            "bindings": dict(test.bindings),
            "excluded": sorted(test.excluded),
            "tags": list(test.tags or []),
        }
        for name, test in sorted(catalog.tests.items())
    }
    payload["groups"] = {name: list(members) for name, members in sorted(catalog.groups.items())}
    print(json.dumps(payload, indent=2))


def _tool_frameworks(simulators: dict[str, Any], tool: str) -> list[str]:
    cfg = simulators.get(tool)
    if not isinstance(cfg, dict):
        return []
    return as_str_list(cfg.get("frameworks"), f"{tool}.frameworks")


def selected_tool(
    flow: Flow, args: argparse.Namespace, simulators: dict[str, Any] | None = None
) -> str:
    tool = args.tool or flow.default_tool
    if simulators is not None and flow.framework:
        capable = _tool_frameworks(simulators, tool)
        if capable and flow.framework not in capable:
            others = sorted(
                name for name in flow.tools if flow.framework in _tool_frameworks(simulators, name)
            )
            hint = (
                f"; `{flow.framework}`-capable tools for dut `{flow.name}`: {', '.join(others)}"
                if others
                else ""
            )
            raise ConfigError(
                f"tool `{tool}` does not support framework `{flow.framework}` "
                f"(`{tool}` supports: {', '.join(capable)}){hint}"
            )
    if tool not in flow.tools:
        raise ConfigError(f"tool `{tool}` is not allowed for flow `{flow.name}`")
    return tool


def _coverage_only_request(args: argparse.Namespace) -> bool:
    stages = set(args.stage or [])
    return bool(stages) and stages.issubset(_COVERAGE_STAGES)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _existing_run_result(
    root: Path,
    flow: Flow,
    args: argparse.Namespace,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Recover tool/coverage intent for merge/report replay on an existing run."""

    if not args.run_dir or not _coverage_only_request(args):
        return None, None
    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    result_path = run_dir / "result.json"
    existing = _read_json_object(result_path)
    if existing is None:
        if not args.dry_run:
            raise ConfigError(f"coverage replay requires an existing result.json: {result_path}")
        return run_dir, None
    if existing.get("flow") != flow.name:
        raise ConfigError(
            f"{result_path}: flow is `{existing.get('flow')}`, expected `{flow.name}`"
        )
    _require_completed_run(existing, result_path)
    existing_tool = existing.get("tool")
    if not isinstance(existing_tool, str) or not existing_tool:
        raise ConfigError(f"{result_path}: missing original tool")
    if args.tool and args.tool != existing_tool:
        raise ConfigError(
            f"requested tool `{args.tool}` does not match existing run tool `{existing_tool}`"
        )
    args.tool = existing_tool
    args.cov = True
    return run_dir, existing


def _require_completed_run(existing: dict[str, Any], result_path: Path) -> None:
    """Coverage is graded over a finished regression only; a truncated run has no grade."""

    if run_is_complete(existing):
        return
    note = incomplete_run_note(existing.get("tests")) or "incomplete run"
    raise ConfigError(
        f"{result_path}: {note}; an interrupted or truncated run is not gradeable, "
        "rerun the regression"
    )


def _status_from_values(values: list[str]) -> str:
    for status in ("ERROR", "TIMEOUT", "FAIL", "UNKNOWN", "PASS"):
        if status in values:
            return status
    return "ERROR"


def _replay_status(existing: dict[str, Any], stages: list[dict[str, Any]]) -> str:
    """Run status over `stages`; an unfinished or interrupted run keeps its recorded status."""

    status_values = [str(stage.get("status", "UNKNOWN")) for stage in stages]
    progress = existing.get("progress")
    if (isinstance(progress, dict) and progress.get("state") != "final") or existing.get(
        "interruption"
    ):
        status_values.append(str(existing.get("status", "UNKNOWN")))
    return _status_from_values(status_values)


def _merge_coverage_replay_result(
    existing: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Preserve simulation history while replacing replayed coverage stages."""

    payload = dict(existing)
    old_stages = [
        stage
        for stage in existing.get("stages", [])
        if isinstance(stage, dict) and stage.get("name") not in _COVERAGE_STAGES
    ]
    new_stages = [stage for stage in current.get("stages", []) if isinstance(stage, dict)]
    stages = [*old_stages, *new_stages]
    status = _replay_status(existing, stages)
    payload.update(
        {
            "status": status,
            "exit_code": exit_code_for_status(status),
            "generated_at": current.get("generated_at"),
            "coverage": current.get("coverage", {}),
            "tool_version": current.get("tool_version", existing.get("tool_version")),
            "tool_versions": current.get("tool_versions", existing.get("tool_versions", {})),
            "overrides": current.get("overrides", existing.get("overrides", {})),
            "stages": stages,
        }
    )
    return payload


def _update_regression_coverage(
    run_dir: Path,
    coverage: dict[str, Any],
    run_status: str,
) -> None:
    path = run_dir / "stages" / "regress" / "regression.json"
    payload = _read_json_object(path)
    if payload is None:
        return
    payload["status"] = run_status
    payload["exit_code"] = exit_code_for_status(run_status)
    artifacts = payload.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        for key in (
            "merged",
            "manifest",
            "report",
            "summary",
            "coverage_details",
            "coverage_details_raw",
            "policy_application",
        ):
            value = coverage.get(key)
            if value:
                artifacts[f"coverage_{key}"] = value
    write_result(path, payload)


def validate_waive_options(args: argparse.Namespace) -> None:
    run_flags = {**_SIM_ONLY_FLAGS, **_FORMAL_ONLY_FLAGS, **_WAIVE_SELECTION_FLAGS}
    for attr, flag in run_flags.items():
        if attr not in _WAIVE_COMPANIONS and _flag_was_set(args, attr):
            raise ConfigError(f"{flag} cannot be combined with --waive")
    if not args.run_dir:
        raise ConfigError("--waive requires --run-dir naming the finished run")


# Options --cov-combine accepts besides --dut, --run-dir, --result, --tool, --framework,
# --overlay, --verbose and --quiet.
_COMBINE_COMPANIONS = {"cov_combine", "fail_under", "dry_run", "timeout"}


def validate_combine_options(args: argparse.Namespace) -> None:
    run_flags = {**_SIM_ONLY_FLAGS, **_FORMAL_ONLY_FLAGS, **_WAIVE_SELECTION_FLAGS}
    for attr, flag in run_flags.items():
        if attr not in _COMBINE_COMPANIONS and _flag_was_set(args, attr):
            hint = (
                "; `--stage cov_merge` re-merges one run's own leaves, `--cov-combine` merges "
                "finished runs"
                if attr == "stage"
                else ""
            )
            raise ConfigError(f"{flag} cannot be combined with --cov-combine{hint}")


def _waive_recorded_run(
    root: Path,
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any], str, str | None]:
    """Read the finished run's result.json and reconcile it with --dut/--tool/--framework."""

    validate_waive_options(args)
    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    result_path = run_dir / "result.json"
    existing = _read_json_object(result_path)
    if existing is None:
        raise ConfigError(f"--waive requires an existing result.json: {result_path}")
    if existing.get("flow") != args.dut:
        raise ConfigError(f"{result_path}: flow is `{existing.get('flow')}`, expected `{args.dut}`")
    tool = existing.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ConfigError(f"{result_path}: missing original tool")
    if args.tool and args.tool != tool:
        raise ConfigError(f"requested tool `{args.tool}` does not match the run's tool `{tool}`")
    recorded_framework = existing.get("framework")
    framework = (
        recorded_framework if isinstance(recorded_framework, str) and recorded_framework else None
    )
    if args.framework and framework and args.framework != framework:
        raise ConfigError(
            f"requested framework `{args.framework}` does not match the run's framework "
            f"`{framework}`"
        )
    return run_dir, existing, tool, args.framework or framework


def _waive_report_record(
    stages: list[dict[str, Any]],
    raw_details: Path,
    result_path: Path,
    run_dir_arg: str,
) -> dict[str, Any]:
    """The cov_report record of a run whose report completed and parsed."""

    hint = (
        "run has no completed coverage report; "
        f"rerun with --run-dir {run_dir_arg} --stage cov_report"
    )
    records = [stage for stage in stages if stage.get("name") == "cov_report"]
    if not records:
        raise ConfigError(f"{result_path}: {hint}")
    record = records[-1]
    if record.get("status") != "PASS":
        kinds = {
            str(bucket.get("kind"))
            for bucket in record.get("failure_buckets") or []
            if isinstance(bucket, dict)
        }
        if not kinds <= _WAIVE_REGRADEABLE_BUCKETS:
            raise ConfigError(f"{result_path}: {hint}")
    if not raw_details.is_file():
        raise ConfigError(f"{raw_details}: {hint}")
    return record


def _native_file_keys(entries: Any) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                keys.add(
                    tuple(str(entry.get(key)) for key in ("tool", "role", "apply_phase", "sha256"))
                )
    return keys


def _require_native_files_unchanged(
    manifest: dict[str, Any],
    policy: CoveragePolicy,
    run_dir_arg: str,
) -> None:
    """Native files act inside the merge and report commands, which a re-grade does not run.

    The manifest records their digests at merge time; the current policy must declare
    the same set.
    """

    recorded_policy = manifest.get("policy")
    recorded = _native_file_keys(
        recorded_policy.get("native_files") if isinstance(recorded_policy, dict) else None
    )
    if recorded != _native_file_keys(native_policy_manifest(policy)):
        raise ConfigError(
            f"{policy.path}: native policy files differ from the ones the report was produced "
            f"with; rerun with --run-dir {run_dir_arg} --stage cov_report"
        )


def _waive_tool_version(summary: dict[str, Any], manifest: dict[str, Any], tool: str) -> str:
    versions = summary.get("tool_versions")
    if isinstance(versions, dict) and isinstance(versions.get(tool), str):
        return versions[tool]
    recorded = manifest.get("tool_version")
    return recorded if isinstance(recorded, str) else "unknown"


def _waive_log_path(run_dir: Path, existing: dict[str, Any], record: dict[str, Any]) -> Path | None:
    """The cov_report stage log under `run_dir`, rebased from the recorded run dir."""

    recorded_log = record.get("log")
    recorded_run_dir = existing.get("run_dir")
    if not isinstance(recorded_log, str) or not isinstance(recorded_run_dir, str):
        return None
    try:
        tail = Path(recorded_log).relative_to(recorded_run_dir)
    except ValueError:
        return None
    candidate = run_dir / tail
    return candidate if candidate.is_file() else None


def waive_run(
    *,
    root: Path,
    flow: Flow,
    tool: str,
    simulators: dict[str, Any],
    existing: dict[str, Any],
    run_dir: Path,
    args: argparse.Namespace,
) -> int:
    """Re-grade the finished run at `run_dir` against a coverage policy.

    Inputs come from the run tree and the policy; the tool version, supported
    metrics and compatibility threshold are the recorded ones. Nothing is written
    until the policy has applied; then the five coverage files, the cov_report
    record, the run status and regression.json follow the new grade.
    """

    if tool not in flow.tools:
        raise ConfigError(f"tool `{tool}` is not allowed for flow `{flow.name}`")
    result_path = run_dir / "result.json"
    _require_completed_run(existing, result_path)
    sim_cfg = merge_simulator_defaults(load_sim_cfg(flow, root), simulators, flow.tools)
    cov = coverage_cfg(sim_cfg)
    tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
    if not tool_cov:
        raise ConfigError(f"no coverage configuration is available for tool `{tool}`")
    paths = coverage_run_paths(run_dir, coverage_merged_name(tool, tool_cov))
    stages = [stage for stage in existing.get("stages", []) if isinstance(stage, dict)]
    record = _waive_report_record(stages, paths.raw_details, result_path, str(args.run_dir))
    manifest = load_manifest(paths.manifest)
    if manifest.get("dut") != flow.name or manifest.get("tool") != tool:
        raise CoverageError(f"{paths.manifest}: coverage manifest DUT/tool does not match the run")
    if not artifact_ready(paths.merged):
        raise CoverageError(f"merged coverage database is missing or empty: {paths.merged}")
    if not paths.report_dir.is_dir():
        raise CoverageError(f"coverage report directory is missing: {paths.report_dir}")
    if args.waive:
        policy_path = repo_path(root, args.waive)
        if not policy_path.is_file():
            raise ConfigError(f"coverage policy does not exist: {policy_path}")
        policy = load_coverage_policy(policy_path, expected_dut=flow.name)
    else:
        policy = resolve_coverage_policy(flow, root, tool, tool_cov)
        if policy is None:
            raise ConfigError(
                f"dut `{flow.name}` has no coverage policy for tool `{tool}`; pass --waive FILE"
            )
    _require_native_files_unchanged(manifest, policy, str(args.run_dir))
    summary = _read_json_object(paths.summary) or {}
    threshold = args.fail_under
    if threshold is None:
        recorded = summary.get("threshold")
        if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
            threshold = float(recorded)
    if threshold is None:
        threshold = coverage_fail_under(tool, tool_cov)
    threshold = threshold if threshold is not None else 0.0
    declared = manifest.get("supported_metrics")
    supported_metrics = (
        [metric for metric in declared if isinstance(metric, str)]
        if isinstance(declared, list)
        else []
    )
    parsed = parse_coverage_run(
        parser=coverage_parser_name(tool_cov),
        dut=flow.name,
        tool=tool,
        manifest=manifest,
        merged=paths.merged,
        report_dir=paths.report_dir,
        log_path=_waive_log_path(run_dir, existing, record),
    )
    raw_text = json_text(parsed.details.to_dict())
    grade = grade_coverage_run(
        parsed=parsed,
        manifest=manifest,
        dut=flow.name,
        root=root,
        tool=tool,
        tool_cov=tool_cov,
        run_dir=run_dir,
        policy=policy,
        threshold=threshold,
        tool_version=_waive_tool_version(summary, manifest, tool),
        supported_metrics=supported_metrics,
    )
    write_json_text(paths.raw_details, raw_text)

    reason = (
        "process completed successfully" if grade.threshold_met else "coverage threshold not met"
    )
    buckets: list[dict[str, Any]] = []
    if not grade.threshold_met:
        buckets.append(
            {
                "kind": "coverage_threshold",
                "signature": reason,
                "count": 1,
                "examples": [record["log"]] if isinstance(record.get("log"), str) else [],
            }
        )
    artifacts = dict(record.get("artifacts") or {})
    artifacts.update(
        {
            "coverage_report": repo_rel(root, paths.report_dir),
            "coverage_summary": repo_rel(root, paths.summary),
            "coverage_details": repo_rel(root, paths.details),
            "coverage_details_raw": repo_rel(root, paths.raw_details),
            "coverage_policy_application": repo_rel(root, paths.application),
        }
    )
    graded = {
        **record,
        "status": grade.status,
        "return_code": 0 if grade.threshold_met else 1,
        "reason": reason,
        "failure_buckets": buckets,
        "artifacts": artifacts,
    }
    new_stages = [graded if stage is record else stage for stage in stages]
    cov_results = [
        StageResult(
            stage=str(stage.get("name")),
            item=stage.get("item") if isinstance(stage.get("item"), str) else None,
            status=str(stage.get("status", "UNKNOWN")),
            return_code=int(stage.get("return_code") or 0),
            duration_sec=float(stage.get("duration_sec") or 0.0),
            started_at=str(stage.get("started_at", "")),
            ended_at=str(stage.get("ended_at", "")),
        )
        for stage in new_stages
        if stage.get("name") in _COVERAGE_STAGES
    ]
    coverage = coverage_summary(cov_results, run_dir, root, True)
    run_status = _replay_status(existing, new_stages)
    payload = dict(existing)
    payload.update(
        {
            "status": run_status,
            "exit_code": exit_code_for_status(run_status),
            "coverage": coverage,
            "stages": new_stages,
        }
    )
    write_result(result_path, payload)
    _update_regression_coverage(run_dir, coverage, run_status)

    console = Console(args.ui, quiet=args.quiet, verbose=args.verbose)
    console.event(
        "result",
        (
            f"coverage={grade.status} status={run_status} "
            f"run_dir={repo_rel(root, run_dir)} json={repo_rel(root, result_path)}"
        ),
        force=True,
    )
    console.close()
    return 0 if grade.threshold_met else 1


def cmd_waive(
    root: Path,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    executors: dict[str, Any],
    args: argparse.Namespace,
    site: SiteLayer | None = None,
) -> int:
    """`--waive`: exit 0 when the re-graded coverage meets its thresholds, 1 when it does
    not, 2 when nothing was written."""

    try:
        run_dir, existing, tool, framework = _waive_recorded_run(root, args)
        flow = resolve_dut(
            root,
            args.dut,
            mode=args.mode,
            framework=framework,
            adopter_overlay=adopter_overlay_path(args),
            site=site,
        )
        validate_flow(flow, root, simulators, policies, executors)
        return waive_run(
            root=root,
            flow=flow,
            tool=tool,
            simulators=simulators,
            existing=existing,
            run_dir=run_dir,
            args=args,
        )
    except (ConfigError, CoverageError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2


def cmd_cov_combine(
    root: Path,
    registries: Registries,
    args: argparse.Namespace,
) -> int:
    """`--cov-combine`: exit 0 when the combined run meets its thresholds, 1 when it does
    not, 2 when the runs cannot be combined."""

    try:
        validate_combine_options(args)
        flow = resolve_dut(
            root,
            args.dut,
            mode=args.mode,
            framework=args.framework,
            adopter_overlay=adopter_overlay_path(args),
            site=registries.site,
        )
        validate_flow(flow, root, registries.simulators, registries.policies, registries.executors)
        return combine_flow(root=root, flow=flow, registries=registries, args=args)
    except (ConfigError, CoverageError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def combine_flow(
    *,
    root: Path,
    flow: Flow,
    registries: Registries,
    args: argparse.Namespace,
) -> int:
    """Combine finished runs into a new run directory and grade it.

    The new run carries the DUT's `cov_merge` and `cov_report` stages over the runs' design
    and merged databases, so its `cov/coverage.json`, report, summary and `result.json`
    have the shape of any coverage run; the manifest's `combine` block names the input runs.
    """

    simulators, policies = registries.simulators, registries.policies
    if registries.site is not None:
        setattr(args, "_site_layer", registries.site.label)
    activate_adopter_overlay_env(flow.raw)
    plan = plan_combine(
        root,
        flow,
        args.tool,
        [Path(value).expanduser() for value in args.cov_combine],
    )
    tool = plan.tool
    if tool not in flow.tools:
        raise ConfigError(f"tool `{tool}` is not allowed for flow `{flow.name}`")
    args.tool = tool
    args.cov = True
    validate_selected_tool_available(tool, simulators, args, flow)
    available = flow_stages(flow)
    for stage in ("cov_merge", "cov_report"):
        if stage not in available:
            raise ConfigError(f"{flow.path}: this flow declares no `{stage}` stage")
    sim_cfg = merge_simulator_defaults(load_sim_cfg(flow, root), simulators, flow.tools)
    catalog = load_test_catalog(flow, root)
    setattr(args, "_cov_combine_plan", plan)

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser()
        if not run_dir.is_absolute():
            run_dir = root / run_dir
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        run_dir = default_run_dir(repo_path(root, flow.root), stamp, tool, "combine")
        # `latest` stays on the last simulation run: the dashboard's default collection
        # follows it, and a combined run has no leaves of its own.
        run_dir = reserve_run_dir(run_dir, args.dry_run)
    result_path = run_dir / "result.json"

    console = Console(args.ui, quiet=args.quiet, verbose=args.verbose)
    args._ui_console = console
    args._ui_leaf_mode = "full"
    commit = plan.commit or "unknown"
    console.event(
        "coverage",
        f"combine runs={len(plan.runs)} frameworks={','.join(plan.frameworks)} "
        f"commit={commit[:12]} inputs="
        + ",".join(repo_rel(root, run.run_dir) or str(run.run_dir) for run in plan.runs),
    )
    for run in plan.runs:
        if run.dirty:
            console.event(
                "warning",
                f"{repo_rel(root, run.run_dir)} was recorded on a dirty tree",
                force=True,
            )
    run_started = time.monotonic()
    results: list[StageResult] = []
    for stage in ("cov_merge", "cov_report"):
        result = run_stage(
            flow, root, sim_cfg, catalog, stage, None, args, tool, run_dir, simulators, policies
        )
        results.append(result)
        if result.status != "PASS" and stage == "cov_merge":
            break
    payload = result_payload(
        flow=flow,
        root=root,
        tool=tool,
        run_dir=run_dir,
        stages=results,
        dry_run=args.dry_run,
        items=[],
        label="combine",
        args=args,
        versions=tool_versions(root),
        git_metadata=git_provenance(root, run_dir),
        planned_leaves=0,
    )
    if not args.dry_run:
        write_result(result_path, payload)
        if args.result:
            export_path = Path(args.result).expanduser()
            if not export_path.is_absolute():
                export_path = root / export_path
            if export_path != result_path:
                write_result(export_path, payload)
    status = str(payload.get("status", aggregate_status(results)))
    console.result(
        status=status,
        elapsed_sec=time.monotonic() - run_started,
        tests=0,
        run_dir=repo_rel(root, run_dir),
        result_json=repo_rel(root, result_path),
        incomplete=None,
    )
    return exit_code_for_status(status)


def flow_executor_name(flow: Flow, args: argparse.Namespace) -> str:
    """The executor a run of ``flow`` selects: ``--executor``, else the profile's default."""
    scheduler = flow.raw.get("scheduler", {})
    if not isinstance(scheduler, dict):
        raise ConfigError(f"{flow.path}: [scheduler] must be a table")
    executor = args.executor or str(scheduler.get("default_executor", "local"))
    allowed = as_str_list(scheduler.get("allowed"), "scheduler.allowed")
    if allowed and executor not in allowed:
        raise ConfigError(f"executor `{executor}` is not allowed for flow `{flow.name}`")
    return executor


def selected_executor(flow: Flow, args: argparse.Namespace, executors: dict[str, Any]) -> str:
    """The selected executor once the registry knows it and its driver can dispatch."""
    executor = flow_executor_name(flow, args)
    cfg = executors.get(executor)
    if not isinstance(cfg, dict):
        raise ConfigError(f"executor `{executor}` is not in the executor registry")
    blocker = dispatch_blocker(executor, cfg)
    if blocker:
        raise ConfigError(blocker)
    return executor


def resource_request(
    args: argparse.Namespace, stage: dict[str, Any], executor_cfg: dict[str, Any]
) -> ResourceRequest:
    """Resources for one stage's leaves: the command line, then the stage table, then the
    executor's defaults."""
    cli = ResourceRequest(
        queue=getattr(args, "queue", None),
        cores=getattr(args, "cores", None),
        mem_mb=getattr(args, "mem_mb", None),
        walltime=getattr(args, "walltime", None),
    )
    return resolve_resources(
        cli,
        ResourceRequest.from_mapping(stage.get("resources")),
        ResourceRequest.from_mapping(executor_cfg.get("defaults")),
    )


def build_resource_request(
    args: argparse.Namespace, stage: dict[str, Any], executor_cfg: dict[str, Any]
) -> ResourceRequest:
    """Resources for one target build: the command line, the build stage's table, then the
    executor's `build_defaults` before its `defaults`."""
    cli = ResourceRequest(
        queue=getattr(args, "queue", None),
        cores=getattr(args, "cores", None),
        mem_mb=getattr(args, "mem_mb", None),
        walltime=getattr(args, "walltime", None),
    )
    return resolve_resources(
        cli,
        ResourceRequest.from_mapping(stage.get("resources")),
        ResourceRequest.from_mapping(executor_cfg.get("build_defaults")),
        ResourceRequest.from_mapping(executor_cfg.get("defaults")),
    )


def tool_needs_license(simulators: dict[str, Any], tool: str) -> bool:
    """True when the registry lists license environment variables for ``tool``."""
    cfg = simulators.get(tool)
    if not isinstance(cfg, dict):
        return False
    return bool(as_str_list(cfg.get("license_env"), f"{tool}.license_env"))


def license_hint(flow: Flow | None, simulators: dict[str, Any], tool: str) -> str:
    """The `(licensed)` pointer for an absent tool, or "" when no license is involved.

    A flow marked `required-commercial` cannot run on open-source tools at all; any other flow
    draws the pointer only when the selected tool itself is a licensed backend.
    """
    if flow is not None and flow.license == "required-commercial":
        return (
            f"`{flow.name}` needs a commercially licensed simulator; "
            "`--list` marks such flows (licensed) — the others run on open-source tools"
        )
    if tool_needs_license(simulators, tool):
        return (
            f"`{tool}` needs a commercial license; `--list` marks such tools (licensed) — "
            "select an unmarked one with `--tool` or load the license environment"
        )
    return ""


def validate_selected_tool_available(
    tool: str,
    simulators: dict[str, Any],
    args: argparse.Namespace,
    flow: Flow | None = None,
) -> None:
    if args.dry_run:
        return
    launch = tool_launch(simulators, tool)
    if locate_tool(launch, launch_env(launch)):
        return
    hint = license_hint(flow, simulators, tool)
    what = f"launcher `{launch.executable}`" if launch.launcher else f"`{launch.binary}`"
    raise ConfigError(
        f"selected tool `{tool}` requires {what} in PATH. "
        f"Load the simulator environment or run `--doctor --tool {tool}` for details."
        + (f" {hint}." if hint else "")
    )


def emit_dry_run_config_summary(
    console: Console,
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    simulators: dict[str, Any],
    tool: str,
    args: argparse.Namespace,
) -> None:
    if not args.dry_run:
        return
    profile = str(flow.raw.get("profile", "none"))
    console.event(
        "config",
        (
            "merge_order=simulator-defaults < "
            f"profile({profile}) < dut({repo_rel(root, flow.path)}) < cli"
        ),
    )

    inherited: list[str] = []
    sim_tool = simulators.get(tool, {})
    if isinstance(sim_tool, dict):
        if isinstance(sim_tool.get("build_defaults"), dict):
            inherited.append(f"simulators.toml[{tool}.build_defaults]")
        if isinstance(sim_tool.get("coverage_defaults"), dict):
            inherited.append(f"simulators.toml[{tool}.coverage_defaults]")
    if "defaults" in sim_cfg:
        inherited.append("profile/DUT [defaults]")
    if "target_defaults" in sim_cfg:
        inherited.append("profile/DUT [target_defaults]")
    build = sim_cfg.get("build", {})
    if isinstance(build, dict) and isinstance(build.get("options"), dict):
        inherited.append("profile/DUT [build.options]")
    if inherited:
        console.event("config", "effective_defaults=" + ", ".join(inherited))


def selected_stages(flow: Flow, args: argparse.Namespace) -> list[str]:
    available = flow_stages(flow)
    # Fail fast: on a flow with no declared coverage stages, --cov would otherwise burn a full
    # compile+sim and only then fail when the post-sim hook finds no coverage artifact.
    if args.cov and "cov_merge" not in available:
        raise ConfigError(
            f"{flow.path}: this flow declares no coverage stages (cov_merge/cov_report); "
            "--cov is unsupported for this DUT"
        )
    if args.stage:
        requested = ["flist" if stage == "filelist" else stage for stage in args.stage]
        if "regress" in requested and "regress" not in available and "sim" in available:
            requested = ["sim" if stage == "regress" else stage for stage in requested]
    elif args.build_only:
        requested = [s for s in ("flist", "hdl_compile", "elaborate") if s in available]
    elif args.run_only:
        requested = (
            ["formal"]
            if flow.kind == "fv" and "formal" in available
            else ["sim" if "sim" in available else "regress"]
        )
    elif args.regress:
        requested = [
            stage for stage in ("flist", "hdl_compile", "elaborate", "sim") if stage in available
        ]
    elif flow.kind == "fv" and "formal" in available:
        # A formal config that declares a filelist stage regenerates the filelist its task file
        # reads before every proof, the way a simulation flow does before its compile.
        requested = [stage for stage in ("flist", "formal") if stage in available]
    else:
        requested = [
            stage for stage in ("flist", "hdl_compile", "elaborate", "sim") if stage in available
        ]

    # With --cov, append the coverage merge/report stages after sim when the flow defines them.
    if args.cov and not args.stage and any(stage in requested for stage in ("sim", "regress")):
        for cov_stage in ("cov_merge", "cov_report"):
            if cov_stage in available and cov_stage not in requested:
                requested.append(cov_stage)

    missing = [stage for stage in requested if stage not in available]
    if missing:
        raise ConfigError(f"flow `{flow.name}` does not define stage(s): {', '.join(missing)}")
    return requested


def requested_items(catalog: TestCatalog, args: argparse.Namespace) -> list[str]:
    if args.items:
        return list(args.items)
    return ["smoke"] if "smoke" in catalog.groups else list(catalog.tests)[:1]


def expand_items(
    catalog: TestCatalog, requested: list[str], need_items: bool, allow_duplicates: bool = False
) -> list[str]:
    if not need_items:
        return []
    expanded: list[str] = []
    seen: set[str] = set()
    for name in requested:
        if name in catalog.groups:
            members = catalog.groups[name]
            # Catalog loading already rejects unresolved members; this keeps directly
            # constructed catalogs on the same contract instead of a downstream KeyError.
            missing = [member for member in members if member not in catalog.tests]
            if missing:
                raise ConfigError(
                    f"group `{name}` references missing test(s): {', '.join(missing)}"
                )
        elif name in catalog.tests:
            members = [name]
        else:
            raise ConfigError(f"unknown test/group `{name}`")
        # De-duplicate by default: a test named by two selected groups runs once, in first-seen
        # order. `--allow-duplicates` opts into intentional repeats.
        for member in members:
            if not allow_duplicates and member in seen:
                continue
            seen.add(member)
            expanded.append(member)
    if not expanded:
        raise ConfigError("no test items selected")
    return expanded


def validate_item_bindings(
    flow: Flow, catalog: TestCatalog, items: list[str], args: argparse.Namespace
) -> list[str]:
    """Enforce that every selected scenario is implemented in the selected framework.

    A selected scenario with no `module` entry for the selected framework is a config error.
    Two escapes apply to group/tag-derived scenarios only, and both are printed and recorded in
    run metadata: a scenario whose binding map declares the framework `false` is skipped
    without any flag, and `--skip-unimplemented` skips the scenarios whose map has no entry.
    An explicitly named `--items` test errors in both cases.
    """
    if not flow.framework:
        return items
    unimplemented = [
        name for name in items if name in catalog.tests and not catalog.tests[name].module
    ]
    if not unimplemented:
        return items
    explicit = set(args.items or [])
    excluded = [name for name in unimplemented if flow.framework in catalog.tests[name].excluded]
    missing = [name for name in unimplemented if name not in set(excluded)]
    blocking = [
        name
        for name in unimplemented
        if name in explicit or (name in set(missing) and not args.skip_unimplemented)
    ]
    if blocking:
        raise ConfigError(_unimplemented_message(flow, catalog, blocking, explicit))
    dropped = set(unimplemented)
    kept = [name for name in items if name not in dropped]
    if not kept:
        raise ConfigError(
            "selection left no runnable scenarios: none of the selected tests are implemented "
            f"for framework `{flow.framework}`"
        )
    setattr(args, "_skipped_excluded", excluded)
    setattr(args, "_skipped_unimplemented", missing)
    return kept


def validate_item_tools(
    catalog: TestCatalog, items: list[str], tool: str, args: argparse.Namespace
) -> list[str]:
    """Drop scenarios the selected tool cannot run, and name the ones dropped.

    A scenario carrying `tools` runs only on the simulators it names. Unlike a missing
    framework binding, this is not a gap someone closes by adding the entry -- it says
    where the scenario's stimulus can work at all -- so a group- or tag-derived selection
    drops it without needing a flag, recorded in run metadata and announced on the
    console. An explicitly named `--items` test still errors instead: the caller asked
    for that scenario by name, and quietly not running it would misreport the run.
    """
    restricted = [
        name
        for name in items
        if name in catalog.tests
        and catalog.tests[name].tools
        and tool not in catalog.tests[name].tools
    ]
    if not restricted:
        return items
    explicit = [name for name in restricted if name in set(args.items or [])]
    if explicit:
        width = max(len(name) for name in explicit)
        lines = "\n".join(
            f"  {name:<{width}}  (runs on: {', '.join(catalog.tests[name].tools)})"
            for name in explicit
        )
        raise ConfigError(
            f"{len(explicit)} explicitly selected scenario(s) cannot run under tool "
            f"`{tool}`:\n{lines}\n  fix: select one of the tools listed with --tool, or "
            f"drop those scenarios from --items"
        )
    kept = [name for name in items if name not in set(restricted)]
    if not kept:
        raise ConfigError(
            f"no selected scenario can run under tool `{tool}`: all {len(restricted)} "
            f"are restricted to other tools"
        )
    setattr(args, "_skipped_wrong_tool", restricted)
    return kept


def _unimplemented_message(
    flow: Flow, catalog: TestCatalog, blocking: list[str], explicit: set[str]
) -> str:
    """Error text naming each blocking scenario, how its map treats the framework, and a fix."""
    fw = flow.framework
    width = max(len(name) for name in blocking)
    lines = []
    for name in blocking:
        test = catalog.tests[name]
        state = f"{fw} = false" if fw in test.excluded else f"no {fw} entry"
        implemented = ", ".join(sorted(test.bindings)) or "none"
        lines.append(f"  {name:<{width}}  ({state}; implemented: {implemented})")
    if any(name in explicit for name in blocking):
        fix = f"  fix: add a `{fw}` module entry or narrow the selection"
    else:
        fix = (
            f"  fix: add a `{fw}` module entry, declare `{fw} = false` in the binding map, "
            "narrow the selection, or pass --skip-unimplemented"
        )
    return (
        f"{len(blocking)} selected scenario(s) are not implemented for framework `{fw}`:\n"
        + "\n".join(lines)
        + f"\n{fix}"
    )


def select_by_tags(catalog: TestCatalog, candidates: list[str], tags: list[str]) -> list[str]:
    """Keep candidate test names whose tags intersect any of `tags`, preserving order."""
    wanted = set(tags)
    return [
        name
        for name in candidates
        if (test := catalog.tests.get(name)) is not None and wanted.intersection(test.tags)
    ]


def run_label(catalog: TestCatalog, requested: list[str], items: list[str]) -> str:
    """Self-describing suffix for the run directory name."""
    for name in requested:
        if name in catalog.groups:
            return name
    if len(items) == 1:
        return items[0]
    if len(items) > 1:
        return "multi"
    return "build"


def scheduler_requested(
    args: argparse.Namespace, requested: list[str], items: list[str], catalog: TestCatalog
) -> bool:
    if args.regress or args.reseed or args.retry or args.max_failures is not None:
        return True
    if args.stage and "regress" in args.stage:
        return True
    if any(name in catalog.groups for name in requested):
        return True
    return len(items) > 1


def validate_regression_seed_options(
    args: argparse.Namespace, randomize_regression_seeds: bool
) -> None:
    if randomize_regression_seeds and args.seed is not None:
        raise ConfigError(
            "--seed cannot be used with regression mode; rerun an individual test "
            "with --stage sim --seed N"
        )


def sim_seed_plan(
    catalog: TestCatalog, sim_cfg: dict[str, Any], args: argparse.Namespace, item: str
) -> list[int]:
    """Deterministic single-simulation seed priority: CLI, testlist, defaults."""
    return [seed_for_item(catalog, sim_cfg, args, item)]


def regression_reseed_count(catalog: TestCatalog, args: argparse.Namespace, item: str) -> int:
    test = catalog.tests.get(item)
    count = (
        test.reseed
        if test and test.reseed is not None
        else (args.reseed if args.reseed is not None else 1)
    )
    if count < 1:
        raise ConfigError("--reseed must be >= 1")
    return count


def random_regression_seed(seen_seeds: set[int]) -> int:
    """Return a positive simulator-compatible seed, avoiding duplicates within this run."""
    while True:
        seed = secrets.randbelow(REGRESSION_SEED_MAX) + 1
        if seed not in seen_seeds:
            seen_seeds.add(seed)
            return seed


def regression_seed_plan(
    catalog: TestCatalog, args: argparse.Namespace, item: str, seen_seeds: set[int]
) -> list[int]:
    count = regression_reseed_count(catalog, args, item)
    return [random_regression_seed(seen_seeds) for _ in range(count)]


def seed_plan(
    catalog: TestCatalog,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    item: str,
    scheduler: bool,
    seen_seeds: set[int] | None = None,
) -> list[int]:
    """Return the seed list for a test item.

    Non-regression simulation remains deterministic. Regression scheduler mode ignores configured
    base seeds and assigns fresh random seeds to each leaf.
    """
    if scheduler:
        return regression_seed_plan(
            catalog, args, item, seen_seeds if seen_seeds is not None else set()
        )
    return sim_seed_plan(catalog, sim_cfg, args, item)


def regression_seed_label(leaves: list[tuple[str, int]]) -> int | str:
    if not leaves:
        return 0
    counts: dict[str, int] = {}
    for item, _ in leaves:
        counts[item] = counts.get(item, 0) + 1
    unique_counts = set(counts.values())
    if len(unique_counts) == 1:
        return unique_counts.pop()
    return "mixed"


def target_plan(
    catalog: TestCatalog,
    sim_cfg: dict[str, Any],
    items: list[str],
    override: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Resolve a target per selected test and return first-seen unique target order.

    ``override`` (``--target``) maps every selected item onto that name.
    Omitted, each test keeps its own target. ``validate_target_plan`` rejects
    an unknown name.
    """
    chosen = override.strip() if isinstance(override, str) and override.strip() else None
    if not items:
        target = chosen or default_target_name(sim_cfg)
        return {}, [target]

    target_by_item: dict[str, str] = {}
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        test = catalog.tests.get(item)
        if test is None:
            raise ConfigError(f"selected item `{item}` is not a test in the catalog")
        target = chosen or resolved_target_name(sim_cfg, test)
        target_by_item[item] = target
        if target not in seen:
            seen.add(target)
            ordered.append(target)
    return target_by_item, ordered


def validate_target_plan(sim_cfg: dict[str, Any], targets: list[str]) -> None:
    defined = target_names(sim_cfg)
    for target in targets:
        if target not in defined:
            raise ConfigError(f"selected target `{target}` is not defined in [targets.{target}]")
        target_cfg = selected_target(sim_cfg, target)
        build_dir = target_cfg.get("build_dir")
        if not isinstance(build_dir, str) or not build_dir:
            raise ConfigError(f"`targets.{target}.build_dir` must be a non-empty string")


def stage_needs_item(stage: str) -> bool:
    # Compile/elaboration may select test-specific targets and source sets. Keep
    # the selected item for stages that run no simulation.
    return stage in {
        "hdl_compile",
        "elaborate",
        "sim",
        "regress",
        "c_compile",
        "formal",
    }


def write_regression_summary(
    root: Path,
    run_dir: Path,
    flow: Flow,
    tool: str,
    jobs: list[dict[str, Any]],
    stages: list[StageResult],
    args: argparse.Namespace,
    items: list[str],
    elapsed_sec: float,
    *,
    status_override: str | None = None,
    progress: dict[str, Any] | None = None,
    interruption: dict[str, Any] | None = None,
    versions: dict[str, str] | None = None,
    git_metadata: dict[str, str] | None = None,
    planned_leaves: int | None = None,
) -> None:
    path = run_dir / "stages" / "regress" / "regression.json"
    write_result(
        path,
        regression_payload(
            flow=flow,
            root=root,
            tool=tool,
            run_dir=run_dir,
            jobs=jobs,
            stages=stages,
            args=args,
            items=items,
            elapsed_sec=elapsed_sec,
            status_override=status_override,
            progress=progress,
            interruption=interruption,
            versions=versions,
            git_metadata=git_metadata,
            planned_leaves=planned_leaves,
        ),
    )


def default_run_dir(dut_dv_root: Path, stamp: str, tool: str, label: str) -> Path:
    # Per-DUT run tree: <dut-dv-root>/build/runs/<stamp>__<tool>__<label>.
    return dut_runs_root(dut_dv_root) / f"{stamp}__{tool}__{label}"


def reserve_run_dir(run_dir: Path, dry_run: bool) -> Path:
    if dry_run:
        return run_dir
    candidate = run_dir
    for idx in range(100):
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = run_dir.with_name(f"{run_dir.name}_{idx + 1:02d}")
    raise ConfigError(f"could not allocate a unique run directory under {run_dir.parent}")


def update_latest_symlink(run_dir: Path, dry_run: bool) -> None:
    """Repoint `<dut-dv-root>/build/runs/latest` at the newest run."""
    if dry_run:
        return
    link = run_dir.parent / "latest"
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            return  # never clobber a real file/dir named `latest`
        link.symlink_to(run_dir.name)
    except OSError:
        pass


def run_flow(
    *,
    root: Path,
    flow: Flow,
    registries: Registries,
    args: argparse.Namespace,
) -> int:
    reset_stage_cancellation()
    simulators, policies = registries.simulators, registries.policies
    if registries.site is not None:
        # result.json records the site file beside the overlay, so a result is attributable
        # to every config layer that produced it.
        setattr(args, "_site_layer", registries.site.label)
    # Before the tool probes and the first stage, so every subprocess environment, env
    # snapshot, and in-process tool runner inherits the overlay's [env].
    overlay_env = activate_adopter_overlay_env(flow.raw)
    replay_run_dir, existing_result = _existing_run_result(root, flow, args)
    tool = selected_tool(flow, args, simulators)
    executor = selected_executor(flow, args, registries.executors)
    executor_cfg = registries.executors[executor]
    setattr(args, "_cluster_executor", executor_cfg.get("kind") == "cluster")
    builds = getattr(args, "builds", None) or executor_builds(executor_cfg)
    if builds == "scheduler" and not args._cluster_executor:
        raise ConfigError("--builds scheduler needs a cluster executor; `local` builds in-process")
    setattr(args, "_scheduler_builds", builds == "scheduler" and not args.dry_run)
    if getattr(args, "walltime", None):
        parse_walltime_sec(str(args.walltime))
    validate_selected_tool_available(tool, simulators, args, flow)
    if args.waves:
        wave_format = resolve_wave_format(args, simulators, tool)
        if not args.dry_run:
            require_verdi_home(tool, wave_format)
    if args.waves_on_fail:
        wave_format = resolve_wave_format(args, simulators, tool, on_fail=True)
        if not args.dry_run:
            require_verdi_home(tool, wave_format)
    sim_cfg = merge_simulator_defaults(load_sim_cfg(flow, root), simulators, flow.tools)
    catalog = load_test_catalog(flow, root)
    if args.run_mode:
        validate_run_mode_request(sim_cfg, str(args.run_mode), "--run-mode")
    stages = selected_stages(flow, args)
    need_items = any(stage_needs_item(stage) for stage in stages)
    requested: list[str] = []
    items: list[str] = []
    if need_items:
        if args.items:
            requested = list(args.items)
            items = expand_items(
                catalog, requested, need_items, allow_duplicates=args.allow_duplicates
            )
        elif args.tag:
            # Tag-only selection starts from the whole catalog (in definition order).
            items = list(catalog.tests)
        else:
            requested = requested_items(catalog, args)
            items = expand_items(
                catalog, requested, need_items, allow_duplicates=args.allow_duplicates
            )
        if args.tag:
            items = select_by_tags(catalog, items, args.tag)
            if not items:
                raise ConfigError(f"no tests match tag(s): {', '.join(args.tag)}")
        items = validate_item_bindings(flow, catalog, items, args)
        items = validate_item_tools(catalog, items, tool, args)

    if need_items and not args.stage and "c_compile" in flow_stages(flow):
        if any(catalog.tests[item].firmware is not None for item in items):
            if "hdl_compile" in stages:
                insert_at = stages.index("hdl_compile")
            elif "elaborate" in stages:
                insert_at = stages.index("elaborate")
            elif "sim" in stages:
                insert_at = stages.index("sim")
            else:
                insert_at = len(stages)
            stages.insert(insert_at, "c_compile")

    scheduler = scheduler_requested(args, requested, items, catalog) if need_items else False
    randomize_regression_seeds = scheduler and any(stage in {"sim", "regress"} for stage in stages)
    validate_regression_seed_options(args, randomize_regression_seeds)
    # Regression/group runs nest every test uniformly; a single explicit test stays flat.
    nest = need_items and bool(items) and scheduler
    label = run_label(catalog, requested, items)
    target_by_item, build_targets = target_plan(
        catalog, sim_cfg, items if need_items else [], override=getattr(args, "target", None)
    )
    if flow.kind == "fv":
        explicit_targets = [item for item in items if catalog.tests[item].target]
        if explicit_targets:
            raise ConfigError(
                "per-test `target` selection is supported for simulation flows only; "
                f"formal item(s) set target: {', '.join(explicit_targets)}"
            )
    validate_target_plan(sim_cfg, build_targets)
    if args.cov and len(build_targets) > 1:
        raise ConfigError(
            "coverage merge accepts one build target; this selection plans "
            + ", ".join(build_targets)
            + ". Pass --target <name> to run every selected test on one elaboration"
        )
    multi_target = len(build_targets) > 1
    setattr(args, "_multi_target_run", multi_target)
    target_cfgs = {
        target: targeted_sim_cfg(sim_cfg, target, force_target_filelist=multi_target)
        for target in build_targets
    }

    def sim_cfg_for_item(item: str | None) -> dict[str, Any]:
        if item is not None:
            return target_cfgs[target_by_item[item]]
        return target_cfgs[build_targets[0]]

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser()
        if not run_dir.is_absolute():
            run_dir = root / run_dir
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        run_dir = default_run_dir(repo_path(root, flow.root), stamp, tool, label)
        run_dir = reserve_run_dir(run_dir, args.dry_run)
        update_latest_symlink(run_dir, args.dry_run)

    result_path = run_dir / "result.json"
    export_path: Path | None = None
    if args.result:
        export_path = Path(args.result).expanduser()
        if not export_path.is_absolute():
            export_path = root / export_path
        if export_path == result_path:
            export_path = None

    leaf_plans_by_stage: dict[int, list[dict[str, Any]]] = {}
    expected_leaves: list[dict[str, Any]] = []
    next_leaf_id = 0
    for stage_index, stage in enumerate(stages):
        if stage not in {"sim", "regress", "formal"}:
            continue
        seen_regression_seeds: set[int] = set()
        stage_plans: list[dict[str, Any]] = []
        for item in items:
            for seed in seed_plan(
                catalog,
                sim_cfg,
                args,
                item,
                scheduler and stage in {"sim", "regress"},
                seen_regression_seeds,
            ):
                identity = {
                    "id": next_leaf_id,
                    "stage": stage,
                    "item": item,
                    "target": target_by_item.get(item),
                    "seed": seed,
                }
                stage_plans.append(identity)
                expected_leaves.append(identity)
                next_leaf_id += 1
        leaf_plans_by_stage[stage_index] = stage_plans

    replaying_coverage = existing_result is not None and replay_run_dir == run_dir
    checkpoint_enabled = bool(expected_leaves) and not args.dry_run and not replaying_coverage
    run_versions = tool_versions(root)
    # Archives the uncommitted diff beside result.json when the tree is dirty, so the
    # commit hash plus that diff identify the sources every leaf of this run compiled.
    run_git = git_provenance(root, run_dir)

    console = Console(args.ui, quiet=args.quiet, verbose=args.verbose)
    args._ui_console = console
    if registries.site is not None:
        console.event("config", registries.site_summary())
    if overlay_env:
        console.event(
            "config",
            "overlay_env=" + " ".join(f"{name}={value}" for name, value in overlay_env.items()),
        )
    args._ui_leaf_mode = "compact" if scheduler else "full"
    for kind in ("skipped_excluded", "skipped_unimplemented"):
        names = list(getattr(args, f"_{kind}", []) or [])
        if names:
            console.event(
                "selection",
                f"{kind}={len(names)} framework={flow.framework} tests={','.join(names)}",
            )
    # Reported on its own line rather than folded into the loop above: this one
    # is keyed on the SIMULATOR, not on the framework, so it carries tool= and
    # would say the wrong thing with framework=.
    skipped_wrong_tool = list(getattr(args, "_skipped_wrong_tool", []) or [])
    if skipped_wrong_tool:
        console.event(
            "selection",
            f"skipped_wrong_tool={len(skipped_wrong_tool)} tool={tool} "
            f"tests={','.join(skipped_wrong_tool)}",
        )
    run_started = time.monotonic()
    results: list[StageResult] = []
    runs_by_item: dict[str, list[tuple[int, StageResult]]] = {}
    regression_jobs: list[dict[str, Any]] = []
    final_failures = 0
    progress_lock = threading.Lock()
    interruption_requested = threading.Event()
    # A signal that arrives while the interruption is being handled sets this: the
    # cancellation stops waiting for confirmations and the summary is written with what it has.
    cleanup_hurry = threading.Event()
    interruption_signal: list[int] = []
    args._cancellation_event = interruption_requested
    active_leaf_ids: set[int] = set()
    completed_leaves_by_id: dict[int, dict[str, Any]] = {}
    # Scheduler jobs of the leaves in flight, by leaf id then task id; a leaf drops its jobs
    # once it is recorded. The checkpoint lists them: after the coordinator dies, they are the
    # only record of which jobs are live.
    leaf_jobs: dict[int, dict[str, dict[str, Any]]] = {}
    cancellation: dict[str, Any] = {}
    checkpoint_sequence = 0

    def with_leaf_jobs(leaf: dict[str, Any]) -> dict[str, Any]:
        entry = dict(leaf)
        jobs = leaf_jobs.get(int(leaf["id"]))
        if jobs:
            entry["jobs"] = [dict(job) for job in jobs.values()]
        return entry

    def checkpoint_progress(state: str) -> dict[str, Any]:
        nonlocal checkpoint_sequence
        with progress_lock:
            checkpoint_sequence += 1
            completed_ids = set(completed_leaves_by_id)
            active_ids = set(active_leaf_ids) - completed_ids
            completed = [
                completed_leaves_by_id[int(leaf["id"])]
                for leaf in expected_leaves
                if int(leaf["id"]) in completed_ids
            ]
            active = [
                with_leaf_jobs(leaf) for leaf in expected_leaves if int(leaf["id"]) in active_ids
            ]
            missing = [
                dict(leaf)
                for leaf in expected_leaves
                if int(leaf["id"]) not in completed_ids | active_ids
            ]
        interrupted = active if state == "interrupted" else []
        visible_active = [] if state == "interrupted" else active
        return {
            "state": state,
            "sequence": checkpoint_sequence,
            "updated_at": datetime.now(UTC).isoformat(),
            "expected_count": len(expected_leaves),
            "completed_count": len(completed),
            "active_count": len(visible_active),
            "missing_count": len(missing),
            "interrupted_count": len(interrupted),
            "active": visible_active,
            "missing": missing,
            "interrupted": interrupted,
        }

    def mark_leaf_active(leaf: dict[str, Any]) -> bool:
        with progress_lock:
            if interruption_requested.is_set():
                return False
            active_leaf_ids.add(int(leaf["id"]))
            return True

    def mark_leaf_completed(leaf: dict[str, Any], result: StageResult) -> None:
        leaf_id = int(leaf["id"])
        completed = {
            **leaf,
            "status": result.status,
            "return_code": result.return_code,
        }
        with progress_lock:
            active_leaf_ids.discard(leaf_id)
            completed_leaves_by_id[leaf_id] = completed
            leaf_jobs.pop(leaf_id, None)

    def note_leaf_job(task: LeafTask, handle: JobHandle) -> None:
        with progress_lock:
            leaf_jobs.setdefault(task.leaf_id, {})[task.task_id] = {
                "task_id": task.task_id,
                "job_id": handle.native_job_id,
            }

    def record_cancellation(
        executor_impl: Executor,
        tasks: dict[str, LeafTask],
        outstanding: list[JobHandle],
        confirmed: dict[str, bool],
        finished: set[str],
        cancel_grace: float,
    ) -> None:
        requested = [handle for handle in outstanding if handle.task_id not in finished]
        unconfirmed = [
            handle.native_job_id
            for handle in outstanding
            if not confirmed.get(handle.task_id, False) and handle.task_id not in finished
        ]
        cancellation.clear()
        cancellation.update(
            {
                "requested": len(requested),
                "confirmed": len(requested) - len(unconfirmed),
                "unconfirmed": unconfirmed,
            }
        )
        if unconfirmed:
            ids = ", ".join(str(job_id) for job_id in unconfirmed)
            console.event(
                "executor",
                f"{len(unconfirmed)} of {len(requested)} cancelled job(s) unconfirmed "
                f"(job ids {ids}); check them with the scheduler by id",
                force=True,
            )

    def cancel_outstanding(
        executor_impl: Executor,
        tasks: dict[str, LeafTask],
        handles: dict[str, JobHandle],
        cancel_grace: float,
    ) -> set[str]:
        """The interrupted-run cleanup both dispatch loops share: a final poll, the cancel
        request with its bounded confirmation wait, and the cancellation record. Returns the
        task ids whose attempt had ended before the cancellation reached them."""
        # From here on a signal unwinds nothing more; it ends the confirmation wait.
        interruption_requested.set()
        outstanding = list(handles.values())
        # A scheduler that stopped answering must not keep the run from its summary.
        try:
            snapshot = executor_impl.poll(outstanding)
        except Exception as exc:  # noqa: BLE001
            console.event("executor", f"final poll failed: {exc}", force=True)
            snapshot = {}
        finished = {
            task_id
            for task_id, seen in snapshot.items()
            if seen.state.terminal and seen.state is not JobState.CANCELLED
        }
        try:
            confirmed = executor_impl.cancel(
                outstanding, grace_sec=cancel_grace, stop=cleanup_hurry
            )
        except Exception as exc:  # noqa: BLE001
            console.event("executor", f"cancel failed: {exc}", force=True)
            confirmed = {}
        request_stage_cancellation()
        record_cancellation(executor_impl, tasks, outstanding, confirmed, finished, cancel_grace)
        return finished

    def leaf_is_completed(leaf: dict[str, Any]) -> bool:
        with progress_lock:
            return int(leaf["id"]) in completed_leaves_by_id

    def write_checkpoint(
        *,
        state: str = "running",
        status: str = "UNKNOWN",
        progress: dict[str, Any] | None = None,
        interruption: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not checkpoint_enabled:
            return None
        progress = progress or checkpoint_progress(state)
        payload = result_payload(
            flow=flow,
            root=root,
            tool=tool,
            run_dir=run_dir,
            stages=list(results),
            dry_run=False,
            items=items,
            label=label,
            args=args,
            executor=executor,
            status_override=status,
            progress=progress,
            interruption=interruption,
            versions=run_versions,
            git_metadata=run_git,
            planned_leaves=len(expected_leaves),
        )
        write_result(result_path, payload)
        if export_path is not None:
            write_result(export_path, payload)
        return payload

    def regression_job(
        stage: str,
        item: str,
        seed: int,
        attempt: int,
        result: StageResult,
        result_json: str | None = None,
    ) -> dict[str, Any]:
        job = {
            "stage": stage,
            "item": item,
            "target": result.target or target_by_item.get(item),
            "seed": seed,
            "attempt": attempt,
            "status": result.status,
            "return_code": result.return_code,
            "reason": result.reason,
            "duration_sec": round(result.duration_sec, 3),
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "log": result.log,
            "artifacts": result.artifacts or {},
            "failure_buckets": result.failure_buckets or [],
            "parser": result.parser,
            "metadata": result.metadata or {},
            "result_json": result_json,
        }
        if result.formal is not None:
            job["formal"] = result.formal
        return job

    # Stage tables are shared across leaves; the shallow copies a debug rerun takes of `args`
    # must share this set so a model built by one attempt counts as built for the rest.
    if not isinstance(getattr(args, "_cocotb_prebuilt_targets", None), set):
        args._cocotb_prebuilt_targets = set()
    resources_by_stage: dict[str, ResourceRequest] = {}

    def stage_resources(stage: str) -> ResourceRequest:
        request = resources_by_stage.get(stage)
        if request is None:
            request = resource_request(args, flow_stages(flow).get(stage, {}), executor_cfg)
            resources_by_stage[stage] = request
        return request

    def leaf_task(
        leaf: dict[str, Any],
        attempt: int,
        *,
        debug_only: bool = False,
        source: StageResult | None = None,
    ) -> LeafTask:
        stage = str(leaf["stage"])
        item = str(leaf["item"])
        seed = int(leaf["seed"])
        # A wave-debug rerun always nests, so its artifacts never overwrite the graded attempt.
        task_nest = nest or debug_only
        overrides: dict[str, Any] = {}
        failure_time = None
        if debug_only:
            log_path = repo_path(root, source.log) if source is not None and source.log else None
            failure_time = find_failure_time_ps(log_path)
            overrides = {
                "waves": args.waves_on_fail,
                "waves_on_fail": None,
                "wave_retention": args.wave_retention or "failed",
            }
        return LeafTask(
            task_id=task_identifier(stage, int(leaf["id"]), attempt, debug_only=debug_only),
            leaf_id=int(leaf["id"]),
            stage=stage,
            item=item,
            seed=seed,
            attempt=attempt,
            run_dir=run_dir,
            leaf_dir=item_artifact_dir(run_dir, item, seed=seed, attempt=attempt, nest=task_nest),
            target=leaf.get("target"),
            nest=task_nest,
            debug_only=debug_only,
            resources=stage_resources(stage),
            args_overrides=overrides,
            wave_failure_time=failure_time,
        )

    def local_runner(task: LeafTask) -> StageResult:
        task_args = attempt_args(args, task) if task.args_overrides or task.debug_only else args
        result, _result_json = execute_attempt(
            flow=flow,
            root=root,
            sim_cfg=sim_cfg_for_item(task.item),
            catalog=catalog,
            task=task,
            args=task_args,
            tool=tool,
            simulators=simulators,
            policies=policies,
        )
        return result

    # Targets whose build ended without a usable model, with the build job that failed them;
    # their leaves grade `dependency_blocked` instead of running.
    blocked_targets: dict[str, dict[str, Any]] = {}

    def run_builds(stage: str, targets: list[str]) -> None:
        """Build every target of ``stage`` and append the results.

        In-process builds stop at the first failure, as a flat run does. Scheduler builds run
        every target as its own job, wait for all of them, and record each failed target as
        blocked, so the other targets' leaves still run.
        """
        if not getattr(args, "_scheduler_builds", False):
            for target in targets:
                result = run_stage(
                    flow,
                    root,
                    target_cfgs[target],
                    catalog,
                    stage,
                    None,
                    args,
                    tool,
                    run_dir,
                    simulators,
                    policies,
                    nest=nest,
                )
                results.append(result)
                if result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}:
                    break
            return
        build_cfg_table = registries.executors[executor]
        limits = executor_limits(build_cfg_table)
        executor_impl = build_executor(
            executor,
            build_cfg_table,
            runner=local_runner,
            max_workers=max(1, len(targets)),
            root=root,
            run_dir=run_dir,
            on_event=lambda text: console.event("executor", text),
        )
        poll_interval = float(limits["poll_interval_sec"])
        cancel_grace = float(limits["cancel_grace_sec"])
        request = build_resource_request(args, flow_stages(flow).get(stage, {}), build_cfg_table)
        commit, dirty = repo_identity(root)
        tasks: dict[str, LeafTask] = {}
        handles: dict[str, JobHandle] = {}
        target_of: dict[str, str] = {}
        for index, target in enumerate(targets):
            safe_target = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in target)
            label = f"build-{stage}-{safe_target}"
            task = LeafTask(
                task_id=label,
                leaf_id=-(index + 1),
                stage=stage,
                item="",
                seed=0,
                attempt=0,
                run_dir=run_dir,
                leaf_dir=run_dir / "stages" / "regress" / "builds" / label,
                target=target,
                nest=False,
                role=BUILD_ROLE,
                resources=request,
            )
            payload = manifest_payload(
                task,
                flow=flow,
                root=root,
                tool=tool,
                executor=executor,
                argv=list(getattr(args, "_raw_argv", []) or []),
                ui_leaf_mode=str(getattr(args, "_ui_leaf_mode", "full")),
                multi_target=multi_target,
                overlay=adopter_overlay_path(args),
                site=registries.site.path if registries.site is not None else None,
                repo_commit=commit,
                repo_dirty=dirty,
            )
            task = replace(
                task, manifest_path=write_manifest(manifest_path(run_dir, label), payload)
            )
            handle = executor_impl.submit(task)
            tasks[label] = task
            handles[label] = handle
            target_of[label] = target
            console.event(
                "build",
                f"{stage} target={target} submitted as job {handle.native_job_id or '(refused)'}",
            )

        def settle(task_id: str, handle: JobHandle, seen: JobObservation) -> None:
            task = tasks[task_id]
            target = target_of[task_id]
            outcome = executor_impl.collect(handle)
            result = outcome.result
            if result is None:
                result = error_result(
                    task,
                    f"environment_error: build {task_id} ended {outcome.state.value.lower()}: "
                    f"{outcome.error or seen.reason or 'no result'}",
                )
                result.metadata = {
                    **(result.metadata or {}),
                    "scheduler": {"job_id": handle.native_job_id, "state": outcome.state.value},
                }
            result.item = None
            result.metadata = {**(result.metadata or {}), "target": target}
            results.append(result)
            console.stage_result(
                stage=stage, status=result.status, duration_sec=result.duration_sec, target=target
            )
            if result.status == "PASS":
                args._cocotb_prebuilt_targets.add(target)
                return
            blocked_targets[target] = {
                "stage": stage,
                "task_id": task_id,
                "job_id": handle.native_job_id,
                "state": outcome.state.value,
                "status": result.status,
                "reason": result.reason,
            }
            console.event(
                "build",
                f"{stage} target={target} {result.status}: its leaves are dependency-blocked",
                force=True,
            )

        try:
            while handles:
                live = list(handles.values())
                executor_impl.wait(live, poll_interval)
                for task_id, seen in executor_impl.poll(live).items():
                    if seen.state.terminal:
                        settle(task_id, handles.pop(task_id), seen)
        except BaseException:
            cancel_outstanding(executor_impl, tasks, handles, cancel_grace)
            executor_impl.close(wait=False)
            raise
        else:
            executor_impl.close(wait=True)

    def attach_wave_debug(
        final: StageResult,
        jobs: list[dict[str, Any]],
        debug_task: LeafTask,
        debug_result: StageResult,
    ) -> None:
        debug_json = repo_rel(root, debug_task.result_json)
        debug_record = regression_job(
            debug_task.stage,
            debug_task.item,
            debug_task.seed,
            debug_task.attempt,
            debug_result,
            debug_json,
        )
        debug_record["debug_only"] = True
        debug_record["status_affects_final_result"] = False
        final.metadata = dict(final.metadata or {})
        final.metadata["wave_debug"] = debug_record
        jobs[-1]["wave_debug"] = debug_record
        jobs[-1].setdefault("artifacts", {})
        if debug_result.artifacts:
            for key, value in debug_result.artifacts.items():
                if key.startswith("wave") or key == "waves":
                    jobs[-1]["artifacts"][f"debug_{key}"] = value
                    final.artifacts = dict(final.artifacts or {})
                    final.artifacts[f"debug_{key}"] = value
        if debug_json:
            jobs[-1]["artifacts"]["debug_result_json"] = debug_json
            final.artifacts = dict(final.artifacts or {})
            final.artifacts["debug_result_json"] = debug_json

    def needs_wave_debug(stage: str, result: StageResult) -> bool:
        return (
            waves_on_fail_requested(args)
            and stage in {"sim", "regress"}
            and result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
        )

    def attempt_is_final(task: LeafTask, result: StageResult) -> bool:
        if result.status != "PASS" and scheduler and task.attempt < (args.retry or 0):
            return False
        return not needs_wave_debug(task.stage, result)

    def run_leaf_stage(stage: str, leaves: list[dict[str, Any]], parallel: bool) -> None:
        """Drive one stage's leaves through the executor until every leaf is recorded."""
        nonlocal final_failures
        # A dry run plans; it submits nothing to a scheduler.
        stage_executor = "local" if args.dry_run else executor
        stage_executor_cfg = registries.executors[stage_executor]
        limits = executor_limits(stage_executor_cfg)
        max_in_flight = args.sim_jobs if parallel else 1
        if limits.get("max_in_flight"):
            max_in_flight = min(max_in_flight, int(limits["max_in_flight"]))
        executor_impl = build_executor(
            stage_executor,
            stage_executor_cfg,
            runner=local_runner,
            max_workers=max_in_flight,
            root=root,
            run_dir=run_dir,
            on_event=lambda text: console.event("executor", text),
        )
        max_in_flight = max(1, min(max_in_flight, executor_impl.max_in_flight))
        submit_cap = executor_impl.submit_batch_size
        poll_interval = float(limits["poll_interval_sec"])
        cancel_grace = float(limits["cancel_grace_sec"])
        blocked_leaves = [leaf for leaf in leaves if leaf.get("target") in blocked_targets]
        pending = deque(leaf for leaf in leaves if leaf.get("target") not in blocked_targets)
        leaf_by_id = {int(leaf["id"]): leaf for leaf in leaves}
        tasks: dict[str, LeafTask] = {}
        handles: dict[str, JobHandle] = {}
        attempts: dict[int, list[StageResult]] = {}
        jobs_by_leaf: dict[int, list[dict[str, Any]]] = {}
        completed_leaves = 0
        identity: list[tuple[str | None, bool | None]] = []

        def build_of(target: str | None) -> dict[str, Any] | None:
            for built in results:
                if built.stage not in {"hdl_compile", "elaborate"} or not built.metadata:
                    continue
                if built.metadata.get("target") == target and built.metadata.get("target_build"):
                    return dict(built.metadata["target_build"])
            return None

        def prepare(task: LeafTask) -> LeafTask:
            """The task with its manifest written, when the executor reads one."""
            if not executor_impl.requires_manifest:
                return task
            if not identity:
                identity.append(repo_identity(root))
            commit, dirty = identity[0]
            payload = manifest_payload(
                task,
                flow=flow,
                root=root,
                tool=tool,
                executor=executor,
                argv=list(getattr(args, "_raw_argv", []) or []),
                ui_leaf_mode=str(getattr(args, "_ui_leaf_mode", "full")),
                multi_target=multi_target,
                overlay=adopter_overlay_path(args),
                site=registries.site.path if registries.site is not None else None,
                repo_commit=commit,
                repo_dirty=dirty,
                target_build=build_of(task.target),
            )
            path = write_manifest(manifest_path(run_dir, task.task_id), payload)
            return replace(task, manifest_path=path)

        def register(task: LeafTask, handle: JobHandle) -> None:
            tasks[task.task_id] = task
            handles[task.task_id] = handle
            if executor_impl.requires_manifest and handle.native_job_id:
                note_leaf_job(task, handle)

        def submit(task: LeafTask) -> None:
            task = prepare(task)
            register(task, executor_impl.submit(task))

        def submit_batch(batch: list[LeafTask]) -> None:
            """First attempts submitted together; a driver with job arrays makes them one.

            Handles are registered as each submission returns, so an interruption part-way
            through the batch cancels every job already submitted.
            """
            prepared = {task.task_id: prepare(task) for task in batch}

            def registered(handles: list[JobHandle]) -> None:
                for handle in handles:
                    register(prepared[handle.task_id], handle)

            executor_impl.submit_many(list(prepared.values()), registered)

        def finish_leaf(
            leaf: dict[str, Any], final: StageResult, jobs: list[dict[str, Any]]
        ) -> None:
            nonlocal completed_leaves, final_failures
            item = str(leaf["item"])
            seed = int(leaf["seed"])
            failed = record_leaf(leaf, final, jobs)
            if scheduler:
                completed_leaves += 1
                console.regression_leaf_done(
                    index=completed_leaves,
                    total=len(leaves),
                    item=item,
                    seed=seed,
                    attempt=max(0, len(jobs) - 1),
                    status=final.status,
                    duration_sec=final.duration_sec,
                    log=final.log,
                    reason=final.reason,
                    target=(final.target or target_by_item.get(item)) if multi_target else None,
                )
            if failed:
                final_failures += 1
                if args.max_failures is not None and final_failures >= args.max_failures:
                    console.event(
                        "note",
                        f"max failures reached ({args.max_failures}); remaining jobs will be skipped",
                    )

        def skip_leaf(leaf: dict[str, Any]) -> None:
            item = str(leaf["item"])
            seed = int(leaf["seed"])
            stamp = datetime.now(UTC).isoformat()
            skipped = StageResult(
                stage=stage,
                item=item,
                status="SKIP",
                return_code=0,
                duration_sec=0.0,
                started_at=stamp,
                ended_at=stamp,
                reason="skipped after --max-failures threshold",
            )
            finish_leaf(leaf, skipped, [regression_job(stage, item, seed, 0, skipped)])

        def block_leaf(leaf: dict[str, Any]) -> None:
            """A leaf whose target has no model: `ERROR` with a `dependency_blocked` bucket."""
            item = str(leaf["item"])
            seed = int(leaf["seed"])
            target = str(leaf.get("target"))
            dependency = blocked_targets[target]
            stamp = datetime.now(UTC).isoformat()
            job = dependency["job_id"] or "not submitted"
            blocked = StageResult(
                stage=stage,
                item=item,
                status="ERROR",
                return_code=exit_code_for_status("ERROR"),
                duration_sec=0.0,
                started_at=stamp,
                ended_at=stamp,
                reason=(
                    f"dependency_blocked: {dependency['stage']} of target {target} "
                    f"{dependency['status']} (job {job}): {dependency['reason']}"
                ),
                failure_buckets=[
                    {
                        "kind": "dependency_blocked",
                        "signature": f"{dependency['stage']} {target}",
                        "count": 1,
                    }
                ],
                metadata={"seed": seed, "attempt": 0, "target": target},
                target=target,
            )
            finish_leaf(leaf, blocked, [regression_job(stage, item, seed, 0, blocked)])

        def attempt_done(task: LeafTask, result: StageResult) -> None:
            leaf = leaf_by_id[task.leaf_id]
            jobs = jobs_by_leaf[task.leaf_id]
            if task.debug_only:
                final = attempts[task.leaf_id][-1]
                attach_wave_debug(final, jobs, task, result)
                finish_leaf(leaf, final, jobs)
                return
            result.result_json = repo_rel(root, task.result_json)
            attempts[task.leaf_id].append(result)
            jobs.append(
                regression_job(
                    stage,
                    task.item,
                    task.seed,
                    task.attempt,
                    result,
                    result.result_json,
                )
            )
            if result.status != "PASS" and scheduler and task.attempt < (args.retry or 0):
                submit(leaf_task(leaf, task.attempt + 1))
                return
            if needs_wave_debug(stage, result):
                debug = leaf_task(leaf, len(jobs), debug_only=True, source=result)
                console.event(
                    "waves",
                    f"rerun item={task.item} seed={task.seed} attempt={debug.attempt} "
                    f"format={resolve_wave_format(attempt_args(args, debug), simulators, tool)}",
                )
                submit(debug)
                return
            finish_leaf(leaf, result, jobs)

        def collect_result(handle: JobHandle, task: LeafTask, reason: str) -> StageResult:
            outcome = executor_impl.collect(handle)
            if outcome.result is not None:
                return outcome.result
            detail = outcome.error or reason or "no result"
            return error_result(
                task,
                f"environment_error: attempt {task.task_id} ended "
                f"{outcome.state.value.lower()}: {detail}",
            )

        for leaf in blocked_leaves:
            block_leaf(leaf)
        try:
            while pending or handles:
                submitted = 0
                batch: list[LeafTask] = []
                while pending and len(handles) + len(batch) < max_in_flight:
                    if submit_cap is not None and submitted >= submit_cap:
                        break
                    submitted += 1
                    leaf = pending.popleft()
                    if (
                        scheduler
                        and args.max_failures is not None
                        and final_failures >= args.max_failures
                    ):
                        skip_leaf(leaf)
                        continue
                    if not mark_leaf_active(leaf):
                        signum = interruption_signal[-1] if interruption_signal else signal.SIGINT
                        raise RunInterrupted(signum)
                    leaf_id = int(leaf["id"])
                    attempts[leaf_id] = []
                    jobs_by_leaf[leaf_id] = []
                    batch.append(leaf_task(leaf, 0))
                if batch:
                    submit_batch(batch)
                if not handles:
                    continue
                live = list(handles.values())
                # With submissions capped per turn, keep filling before the first real wait.
                throttled = bool(pending) and len(handles) < max_in_flight
                executor_impl.wait(live, 0.0 if throttled else poll_interval)
                for task_id, observation in executor_impl.poll(live).items():
                    if not observation.state.terminal:
                        continue
                    handle = handles.pop(task_id)
                    task = tasks.pop(task_id)
                    attempt_done(task, collect_result(handle, task, observation.reason))
        except BaseException:
            # Only an attempt that had ended before the interruption counts as a completed
            # leaf; whatever the cancellation ends is interrupted, whichever result it wrote.
            outstanding = list(handles.values())
            finished = cancel_outstanding(executor_impl, tasks, handles, cancel_grace)
            for handle in outstanding:
                if handle.task_id not in finished:
                    continue
                task = tasks[handle.task_id]
                leaf = leaf_by_id[task.leaf_id]
                if task.debug_only or leaf_is_completed(leaf):
                    continue
                outcome = executor_impl.collect(handle)
                if outcome.result is None or not attempt_is_final(task, outcome.result):
                    continue
                jobs = [
                    *jobs_by_leaf[task.leaf_id],
                    regression_job(
                        stage,
                        task.item,
                        task.seed,
                        task.attempt,
                        outcome.result,
                        repo_rel(root, task.result_json),
                    ),
                ]
                record_leaf(leaf, outcome.result, jobs, refresh_checkpoint=False)
            executor_impl.close(wait=False)
            raise
        else:
            executor_impl.close(wait=True)

    def record_leaf(
        leaf: dict[str, Any],
        result: StageResult,
        jobs: list[dict[str, Any]],
        *,
        refresh_checkpoint: bool = True,
    ) -> bool:
        item = str(leaf["item"])
        seed = int(leaf["seed"])
        results.append(result)
        runs_by_item.setdefault(item, []).append((seed, result))
        regression_jobs.extend(jobs)
        mark_leaf_completed(leaf, result)
        if refresh_checkpoint:
            write_checkpoint()
        return scheduler and result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}

    def needs_parallel_cocotb_prebuild(stage: str, target: str) -> bool:
        available = flow_stages(flow)
        sim_stage = available.get(stage)
        hdl_compile_stage = available.get("hdl_compile")
        elaborate_stage = available.get("elaborate")
        cocotb_build_defined = (
            isinstance(hdl_compile_stage, dict)
            and str(hdl_compile_stage.get("kind", "")) == "cocotb_build"
        ) or (
            isinstance(elaborate_stage, dict)
            and str(elaborate_stage.get("kind", "")) == "cocotb_build"
        )
        return (
            stage in {"sim", "regress"}
            and isinstance(sim_stage, dict)
            and str(sim_stage.get("kind", "")) in {"cocotb_sim", "cocotb_verilator"}
            and cocotb_build_defined
            and target not in getattr(args, "_cocotb_prebuilt_targets", set())
        )

    previous_signal_handlers: dict[int, Any] = {}

    def interrupt_handler(signum: int, _frame: Any) -> None:
        interruption_signal.append(signum)
        if interruption_requested.is_set():
            cleanup_hurry.set()
            return
        interruption_requested.set()
        raise RunInterrupted(signum)

    try:
        if checkpoint_enabled:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_signal_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupt_handler)
            write_checkpoint()
        console.run_header(
            flow=flow.name,
            tool=tool,
            run_dir=repo_rel(root, run_dir),
            items=len(items) if need_items else 0,
            stages=stages,
            verbose=args.verbose,
            jobs=args.sim_jobs,
            executor=executor,
            mode="regression" if scheduler else None,
        )
        emit_dry_run_config_summary(console, flow, root, sim_cfg, simulators, tool, args)
        for stage_index, stage in enumerate(stages):
            if stage in {"flist", "hdl_compile", "elaborate"}:
                if stage == "flist":
                    for target in build_targets:
                        result = run_stage(
                            flow,
                            root,
                            target_cfgs[target],
                            catalog,
                            stage,
                            None,
                            args,
                            tool,
                            run_dir,
                            simulators,
                            policies,
                            nest=nest,
                        )
                        results.append(result)
                        if result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}:
                            break
                else:
                    run_builds(
                        stage, [target for target in build_targets if target not in blocked_targets]
                    )
                # A failed scheduler build blocks its target's leaves in the sim stage instead
                # of ending the run here, so the record accounts for every planned leaf.
                if aggregate_status(results) in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"} and (
                    stage == "flist" or not getattr(args, "_scheduler_builds", False)
                ):
                    break
            elif stage in {"sim", "regress", "formal"}:
                leaves = leaf_plans_by_stage.get(stage_index, [])
                leaf_item_width = max(
                    (len(str(leaf["item"])) for leaf in leaves),
                    default=44,
                )
                leaf_seed_width = max(
                    (len(str(leaf["seed"])) for leaf in leaves),
                    default=8,
                )
                parallel = (
                    scheduler
                    and args.sim_jobs > 1
                    and len(leaves) > 1
                    and args.max_failures is None
                    and not args.dry_run
                )
                if parallel:
                    missing_prebuilds = [
                        target
                        for target in build_targets
                        if needs_parallel_cocotb_prebuild(stage, target)
                    ]
                    prebuild_stage = (
                        "hdl_compile" if "hdl_compile" in flow_stages(flow) else "elaborate"
                    )
                    for target in missing_prebuilds:
                        console.event(
                            "scheduler",
                            f"pre-building cocotb model for target `{target}` before parallel sim",
                        )
                    if missing_prebuilds:
                        run_builds(prebuild_stage, missing_prebuilds)
                    if (
                        missing_prebuilds
                        and aggregate_status(results) in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
                        and not getattr(args, "_scheduler_builds", False)
                    ):
                        break
                if scheduler:
                    console.regression_start(
                        total=len(leaves),
                        jobs=args.sim_jobs,
                        executor=executor,
                        seeds=regression_seed_label(
                            [(str(leaf["item"]), int(leaf["seed"])) for leaf in leaves]
                        ),
                        retry=args.retry or 0,
                        item_width=leaf_item_width,
                        seed_width=leaf_seed_width,
                    )
                run_leaf_stage(stage, leaves, parallel)
            else:
                if stage == "c_compile" and items:
                    for item in items:
                        item_cfg = sim_cfg_for_item(item)
                        seed = seed_for_item(catalog, item_cfg, args, item)
                        results.append(
                            run_stage(
                                flow,
                                root,
                                item_cfg,
                                catalog,
                                stage,
                                item,
                                args,
                                tool,
                                run_dir,
                                simulators,
                                policies,
                                nest=nest,
                                seed_override=seed,
                            )
                        )
                else:
                    results.append(
                        run_stage(
                            flow,
                            root,
                            sim_cfg,
                            catalog,
                            stage,
                            None,
                            args,
                            tool,
                            run_dir,
                            simulators,
                            policies,
                            nest=nest,
                        )
                    )
            if not scheduler and aggregate_status(results) in {
                "FAIL",
                "ERROR",
                "TIMEOUT",
                "UNKNOWN",
            }:
                break

        # Per-test rollups across seeds/attempts. Only when nested: in a flat run the leaf fragment is
        # already the per-test `<test>/result.json`, so writing a rollup there would clobber it.
        if nest and not args.dry_run:
            for item, runs in runs_by_item.items():
                write_result(
                    run_dir / item / "result.json",
                    rollup_payload(
                        flow=flow, root=root, tool=tool, run_dir=run_dir, item=item, runs=runs
                    ),
                )
            write_regression_summary(
                root,
                run_dir,
                flow,
                tool,
                regression_jobs,
                results,
                args,
                items,
                time.monotonic() - run_started,
                versions=run_versions,
                git_metadata=run_git,
                planned_leaves=len(expected_leaves),
            )
        if scheduler:
            console.regression_summary(
                runs_by_item,
                ordered_items=items,
                elapsed_sec=time.monotonic() - run_started,
                planned=len(expected_leaves),
            )

        # Structured-result guarantee, leafless case: a non-passing run in which no sim
        # leaf executed (compile/elaboration/filelist failure) gets one run-level stage
        # XML so the failure is visible to JUnit consumers. Runs before result_payload
        # so the failing stage's artifact pointer lands in result.json; skipped on
        # coverage replay, which re-enters a run dir whose leaves did not rerun.
        if not args.dry_run and not replaying_coverage:
            try:
                materialize_stage_junit(
                    flow=flow,
                    root=root,
                    run_dir=run_dir,
                    tool=tool,
                    stages=results,
                )
            except Exception as exc:  # noqa: BLE001
                console.event("warning", f"junit synthesis failed: {exc}", force=True)
        payload = result_payload(
            flow=flow,
            root=root,
            tool=tool,
            run_dir=run_dir,
            stages=results,
            dry_run=args.dry_run,
            items=items,
            label=label,
            args=args,
            executor=executor,
            versions=run_versions,
            git_metadata=run_git,
            planned_leaves=len(expected_leaves),
        )
        if replaying_coverage:
            payload = _merge_coverage_replay_result(existing_result, payload)
        if not args.dry_run:
            write_result(result_path, payload)
            if export_path is not None:
                write_result(export_path, payload)
            if replaying_coverage:
                _update_regression_coverage(
                    run_dir,
                    payload.get("coverage", {}),
                    str(payload.get("status", "ERROR")),
                )
        status = str(payload.get("status", aggregate_status(results)))
        console.result(
            status=status,
            elapsed_sec=time.monotonic() - run_started,
            tests=len(items) if need_items else 0,
            run_dir=repo_rel(root, run_dir),
            result_json=repo_rel(root, result_path),
            incomplete=incomplete_run_note(payload.get("tests")),
        )
        return exit_code_for_status(status)
    except (RunInterrupted, ClusterError) as exc:
        interruption_requested.set()
        # The signal unwound run_stage past its console.suppress exit, so this thread is
        # still muted; everything below is for the operator.
        console.clear_suppression()
        request_stage_cancellation()
        if isinstance(exc, RunInterrupted):
            signal_name = signal.Signals(exc.signum).name
            interruption = {
                "kind": "signal",
                "signal": signal_name,
                "signal_number": exc.signum,
                "reason": f"run interrupted by {signal_name}",
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            exit_code = 128 + exc.signum
        else:
            interruption = {
                "kind": "executor",
                "executor": executor,
                "reason": f"run aborted by executor `{executor}`: {exc}",
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            exit_code = exit_code_for_status("ERROR")
        if cancellation.get("unconfirmed"):
            interruption["cancellation"] = dict(cancellation)
        progress = checkpoint_progress("interrupted")
        elapsed_sec = time.monotonic() - run_started
        if nest and checkpoint_enabled:
            write_regression_summary(
                root,
                run_dir,
                flow,
                tool,
                regression_jobs,
                results,
                args,
                items,
                elapsed_sec,
                status_override="ERROR",
                progress=progress,
                interruption=interruption,
                versions=run_versions,
                git_metadata=run_git,
                planned_leaves=len(expected_leaves),
            )
        payload = write_checkpoint(
            state="interrupted",
            status="ERROR",
            progress=progress,
            interruption=interruption,
        )
        if payload is not None:
            try:
                materialize_interruption_junit(
                    flow=flow,
                    root=root,
                    run_dir=run_dir,
                    tool=tool,
                    interruption=interruption,
                    progress=progress,
                )
            except Exception as junit_exc:  # noqa: BLE001
                console.event("warning", f"junit synthesis failed: {junit_exc}", force=True)
        console.event("error", interruption["reason"], force=True)
        console.result(
            status="ERROR",
            elapsed_sec=elapsed_sec,
            tests=len(items) if need_items else 0,
            run_dir=repo_rel(root, run_dir),
            result_json=repo_rel(root, result_path),
            incomplete=incomplete_run_note((payload or {}).get("tests"))
            or f"incomplete run: {progress['completed_count']} of "
            f"{progress['expected_count']} planned leaves ran",
            force=True,
        )
        return exit_code
    finally:
        for signum, previous_handler in previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
        console.close()


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if not raw_argv:
        # A bare invocation is a person exploring, not a run: show the full help page
        # (with the examples) instead of the --dut-required error.
        parse_args(["--help"])
    args = parse_args(raw_argv)
    args._raw_argv = raw_argv
    try:
        validate_mode_options(args)
        if args.json and not args.list:
            raise ConfigError("--json applies to --list only")
        root = repo_root(Path(__file__))

        # Diagnostics report their own findings (and must not be preempted by the fail-fast
        # validate_all below), so dispatch them first.
        if args.validate_configs:
            return cmd_validate_configs(root, adopter_overlay_path(args))
        if args.doctor:
            return cmd_doctor(root, args)

        duts, registries, formal_views = validate_all(root)
        absent_sim = unavailable_sim_views(root, registries.site)
        simulators, executors, policies = (
            registries.simulators,
            registries.executors,
            registries.policies,
        )

        if args.list:
            if args.dut:
                flow = resolve_dut(
                    root,
                    args.dut,
                    mode=args.mode,
                    framework=args.framework,
                    adopter_overlay=adopter_overlay_path(args),
                    site=registries.site,
                )
                validate_flow(flow, root, simulators, policies, executors)
                if args.json:
                    list_flow_detail_json(flow, root)
                else:
                    list_flow_detail(flow, root)
            elif args.json:
                list_flows_json(root, duts, formal_views, absent_sim, registries.site)
            else:
                list_flows(duts, simulators, formal_views, absent_sim, root, registries.site)
            return 0

        if not args.dut:
            raise ConfigError(
                "--dut is required unless --list, --validate-configs, or --doctor is used "
                "(start with --list to see the selectable DUTs)"
            )
        if args.dut not in duts and args.dut not in absent_sim:
            raise ConfigError(f"unknown DUT `{args.dut}`")
        if args.waive is not None:
            return cmd_waive(root, simulators, policies, executors, args, site=registries.site)
        if args.cov_combine:
            return cmd_cov_combine(root, registries, args)
        flow = resolve_dut(
            root,
            args.dut,
            mode=args.mode,
            framework=args.framework,
            adopter_overlay=adopter_overlay_path(args),
            site=registries.site,
        )
        validate_flow(flow, root, simulators, policies, executors)
        return run_flow(root=root, flow=flow, registries=registries, args=args)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
