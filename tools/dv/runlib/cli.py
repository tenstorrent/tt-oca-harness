"""Command-line orchestration for the native DV runner."""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.metadata
import json
import os
import secrets
import shutil
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC
from .config import (
    CANONICAL_STAGES,
    as_str_list,
    default_target_name,
    flow_stages,
    load_executors,
    load_sim_cfg,
    load_simulators,
    load_test_catalog,
    merge_simulator_defaults,
    resolved_target_name,
    selected_target,
    targeted_sim_cfg,
    target_names,
    validate_native_config_shape,
)
from .duts import load_duts, resolve_dut
from .logparse import validate_parser_extensions, validate_parser_registry
from .models import ConfigError, Flow, StageResult, TestCatalog
from .paths import configs_root, dut_runs_root, repo_path, repo_rel, repo_root
from .results import (
    aggregate_status,
    exit_code_for_status,
    fragment_payload,
    regression_payload,
    result_payload,
    rollup_payload,
    write_result,
)
from .stages import item_artifact_dir, run_stage, seed_for_item
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
_COVERAGE_STAGES = {"cov_merge", "cov_report"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        usage="%(prog)s [options]",
        description=(
            "Native OSS DV/FV launcher for listing DUTs, validating configs, "
            "and running simulation or formal flows."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              python3 tools/dv/run_dv.py --list
              python3 tools/dv/run_dv.py --validate-configs
              python3 tools/dv/run_dv.py --doctor --dut dtp
              python3 tools/dv/run_dv.py --dut smc_wrapper --list
              python3 tools/dv/run_dv.py --dut smc_wrapper --items smoke --tool verilator --dry-run
              python3 tools/dv/run_dv.py --dut smc_wrapper --build-only --dry-run
              python3 tools/dv/run_dv.py --dut smc_wrapper --items smoke --regress --reseed 10
              python3 tools/dv/run_dv.py --dut smc_wrapper --items smoke --waves-on-fail fst
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
        "--items",
        nargs="+",
        metavar="ITEM",
        help="Test/check names or groups",
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
    common.add_argument("--tool", metavar="TOOL", help="Backend tool override")
    common.add_argument("--run-mode", metavar="NAME", help="Named run mode from sim cfg")

    actions = parser.add_argument_group("Actions And Introspection")
    actions.add_argument(
        "--list",
        action="store_true",
        help="List configured DUTs or selected DUT details",
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
    stages.add_argument("--stage", action="append", metavar="NAME", help="Native stage to run")
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
    output.add_argument("--run-dir", metavar="DIR", help="Run output directory")
    output.add_argument("--result", metavar="PATH", help="Result JSON output path")
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
        help="Backend compile/build job count; uses --sim-jobs when omitted",
    )
    parallel.add_argument("--executor", default=None, metavar="NAME", help="Executor backend")
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
    regression.add_argument("--seed", type=int, metavar="N", help="Seed override")
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
        help="Enable waves, optionally naming a format",
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
    coverage.add_argument("--cov", action="store_true", help="Enable coverage where supported")
    coverage.add_argument(
        "--fail-under",
        type=float,
        metavar="PCT",
        help="Coverage report threshold override",
    )

    backend = parser.add_argument_group("Backend Pass-Through Args")
    backend.add_argument(
        "--define",
        action="append",
        metavar="VALUE",
        help="Extra +define+ value",
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


def validate_mode_options(args: argparse.Namespace) -> None:
    sim_only = {
        "seed": "--seed",
        "reseed": "--reseed",
        "retry": "--retry",
        "max_failures": "--max-failures",
        "run_mode": "--run-mode",
        "waves": "--waves",
        "waves_on_fail": "--waves-on-fail",
        "wave_start": "--wave-start",
        "wave_end": "--wave-end",
        "wave_window": "--wave-window",
        "wave_margin": "--wave-margin",
        "wave_retention": "--wave-retention",
        "cov": "--cov",
        "fail_under": "--fail-under",
        "rebuild": "--rebuild",
        "define": "--define",
        "comp_arg": "--comp-arg",
        "c_arg": "--c-arg",
        "sim_arg": "--sim-arg",
        "plusarg": "--plusarg",
        "regress": "--regress",
    }
    formal_only = {
        "proof_depth": "--proof-depth",
        "formal_arg": "--formal-arg",
        "app": "--app",
    }
    if args.mode == "formal":
        for attr, flag in sim_only.items():
            if _flag_was_set(args, attr):
                raise ConfigError(f"{flag} is simulation-only; selected mode is formal")
    else:
        for attr, flag in formal_only.items():
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


def validate_duplicate_purpose_keys(flow: Flow, sim_cfg: dict[str, Any], simulators: dict[str, Any]) -> None:
    errors: list[str] = []
    defaults = sim_cfg.get("defaults", {})
    if isinstance(defaults, dict) and "tool" in defaults:
        errors.append("[defaults].tool duplicates top-level default_tool; use default_tool")

    run_modes = sim_cfg.get("run_modes", {})
    if isinstance(run_modes, dict):
        for name, mode in sorted(run_modes.items()):
            if isinstance(mode, dict) and "tags" in mode:
                errors.append(f"[run_modes.{name}].tags duplicates testlist tags; remove it")

    build_options = sim_cfg.get("build", {}).get("options", {}) if isinstance(sim_cfg.get("build"), dict) else {}
    if isinstance(build_options, dict):
        for key in ("ccache", "output_split"):
            if key in build_options:
                errors.append(f"[build.options].{key} is Verilator-specific; use [build.verilator].{key}")

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
                    errors.append(f"[{section_name}.{target_name}].{old_key} is deprecated; use {new_key}")

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
                        errors.append(f"[coverage.{tool}].{old_key} is deprecated; use generic build_args/compile_args/sim_args/test_args")
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


def validate_flow(
    flow: Flow,
    root: Path,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    executors: dict[str, Any] | None = None,
) -> None:
    if not (root / flow.root).exists():
        raise ConfigError(f"{flow.path}: root path does not exist: {flow.root}")
    for tool in flow.tools:
        if tool not in simulators:
            raise ConfigError(f"{flow.path}: tool `{tool}` missing from simulators.toml")
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
    from .coverage_policy import load_coverage_policy

    coverage = sim_cfg.get("coverage", {})
    if isinstance(coverage, dict):
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
                        repo_candidate
                        if repo_candidate.is_file()
                        else flow.path.parent / candidate
                    )
            else:
                candidate = (
                    flow.path.parent
                    / "cov"
                    / "config"
                    / tool
                    / "coverage_policy.toml"
                )
            if candidate.is_file():
                load_coverage_policy(candidate, expected_dut=flow.name)
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


def validate_all(root: Path) -> tuple[dict[str, Flow], dict[str, Any], dict[str, Any], dict[str, Any]]:
    duts = load_duts(root)
    simulators = load_simulators(root)
    executors = load_executors(root)
    policies = validate_parser_registry(root)
    for flow in duts.values():
        validate_flow(flow, root, simulators, policies, executors)
    return duts, simulators, policies, executors


def cmd_validate_configs(root: Path) -> int:
    """Validate every config and print a per-DUT summary.

    Unlike the run path (which fails fast), this reports every DUT's status in one pass so a user
    sees all config problems at once instead of fixing them one re-run at a time.
    """
    print(f"Validating configs in {repo_rel(root, configs_root(root))}\n")

    # The registries are structural: per-flow validation cannot run without them, so a failure here
    # is reported on its own and stops the report.
    try:
        simulators = load_simulators(root)
        executors = load_executors(root)
        policies = validate_parser_registry(root)
    except ConfigError as exc:
        print(f"  registries       FAIL: {exc}")
        print("\nResult: registry error — fix it before flows can be validated")
        return 2
    print("  simulators.toml  OK")
    print("  executors.toml   OK")
    print("  parsers.toml     OK")

    try:
        duts = load_duts(root)
    except ConfigError as exc:
        print(f"  DUT discovery    FAIL: {exc}")
        print("\nResult: could not load the DUT set")
        return 2

    failures = 0
    for name in sorted(duts):
        try:
            validate_flow(duts[name], root, simulators, policies, executors)
            print(f"  {name:<16} OK")
        except ConfigError as exc:
            failures += 1
            print(f"  {name:<16} FAIL: {exc}")

    total = len(duts)
    print(f"\nResult: {total} DUT(s): {total - failures} OK, {failures} FAILED")
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
        f">={_version_text(SUPPORTED_PYTHON_MIN)},"
        f"<{_version_text(SUPPORTED_PYTHON_MAX_EXCLUSIVE)}"
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


def _try_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, "import OK"
    except Exception as exc:  # noqa: BLE001 - doctor must report actionable import failures.
        return False, f"{type(exc).__name__}: {exc}"


def _doctor_python_environment(root: Path, flow: Flow | None) -> bool:
    """Check Python package/import readiness for OSS DV contributor flows.

    Returns True when a selected flow cannot run in the current Python environment.
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

    distributions = [
        ("shared dv package", "ocah-dv"),
        ("cocotb", "cocotb"),
        ("pyuvm", "pyuvm"),
        ("cocotbext-axi", "cocotbext-axi"),
        ("cocotbext-jtag", "cocotbext-jtag"),
        ("cocotbext-i2c", "cocotbext-i2c"),
    ]
    for label, dist_name in distributions:
        version = _dist_version(dist_name)
        if version is None:
            failed = True
            _print_doctor_row(
                label,
                "FAIL",
                "missing distribution "
                f"`{dist_name}`; launch via `python3 tools/dv/run_dv.py` (uv-managed) "
                "or run `uv sync --locked --group dv` at the repository root",
            )
        else:
            _print_doctor_row(label, "OK", version)

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

    ok, detail = _try_import("ocah_axi_vip")
    _print_doctor_row("import ocah_axi_vip", "OK" if ok else "FAIL", detail)
    failed |= not ok

    if flow is not None and flow.framework == "cocotb":
        dut_module = flow.name
        ok, detail = _try_import(dut_module)
        _print_doctor_row(f"import {dut_module}", "OK" if ok else "FAIL", detail)
        failed |= not ok

        env_module = f"{dut_module}.cocotb.env"
        try:
            env_spec = importlib.util.find_spec(env_module)
        except ModuleNotFoundError:
            env_spec = None
        if env_spec is not None:
            ok, detail = _try_import(env_module)
            _print_doctor_row(f"import {env_module}", "OK" if ok else "FAIL", detail)
            failed |= not ok
    elif flow is not None:
        _print_doctor_row(
            "DUT-local import", "SKIP", f"framework `{flow.framework}` has no DUT Python package"
        )
    else:
        _print_doctor_row("DUT-local import", "SKIP", "select --dut <name> to check one DUT package")

    print()
    return failed


def cmd_doctor(root: Path, args: argparse.Namespace) -> int:
    """Report whether the tools a run needs are actually installed on this machine.

    `--validate-configs` answers "is my config correct?"; `--doctor` answers "can I actually run it
    here?" — it confirms configs load, then probes tool binaries and license-env presence.
    """
    try:
        simulators = load_simulators(root)
        executors = load_executors(root)
        policies = validate_parser_registry(root)
        duts = load_duts(root)
        for flow in duts.values():
            validate_flow(flow, root, simulators, policies, executors)
    except ConfigError as exc:
        print(f"configs : FAIL: {exc}")
        print("\nResult: fix config errors first (run --validate-configs for the full list)")
        return 2
    print("configs : OK")

    flow: Flow | None = None
    if args.dut:
        try:
            flow = resolve_dut(root, args.dut, mode=args.mode)
            validate_flow(flow, root, simulators, policies, executors)
        except ConfigError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    required: str | None = None
    if flow is not None:
        tools = list(flow.tools)
        required = selected_tool(flow, args)
        scope = f"DUT `{flow.name}` (would run with: {required})"
    elif args.tool:
        tools = [args.tool]
        required = args.tool
        scope = f"tool `{args.tool}`"
    else:
        tools = sorted(simulators)
        scope = "all registered tools (survey)"

    print(f"checking: {scope}\n")
    python_failed = _doctor_python_environment(root, flow)

    print(f"  {'tool':<10} {'binary':<12} {'status':<26} licenses")
    missing_required = False
    for tool in tools:
        cfg = simulators.get(tool)
        if not isinstance(cfg, dict):
            print(f"  {tool:<10} {'?':<12} {'NOT IN REGISTRY':<26} -")
            if tool == required:
                missing_required = True
            continue
        binary = str(cfg.get("binary", tool))
        found = shutil.which(binary)
        status = f"found: {found}" if found else "MISSING from PATH"
        lic_env = as_str_list(cfg.get("license_env"), f"{tool}.license_env")
        if not lic_env:
            lic = "none needed"
        else:
            set_count = sum(1 for var in lic_env if os.environ.get(var))
            lic = f"{set_count}/{len(lic_env)} env set"
        note = ""
        if not found:
            note = "  <- required" if tool == required else "  (optional)"
            if tool == required:
                missing_required = True
        print(f"  {tool:<10} {binary:<12} {status:<26} {lic}{note}")

    print()
    if required is None:
        print("Result: survey only (no --dut/--tool selected); missing tools are informational")
        return 0
    if python_failed and flow is not None:
        print("Result: Python/package environment is NOT ready for this flow")
        return 2
    if missing_required:
        print(f"Result: required tool `{required}` is NOT available — this flow cannot run here")
        return 2
    print(f"Result: required tool `{required}` is available")
    return 0


def list_flows(flows: dict[str, Flow]) -> None:
    for flow in sorted(flows.values(), key=lambda item: item.name):
        print(f"{flow.name:<16} {flow.kind:<3} {flow.framework:<8} {flow.description}")


def list_flow_detail(flow: Flow, root: Path) -> None:
    catalog = load_test_catalog(flow, root)
    print(f"name       : {flow.name}")
    print(f"kind       : {flow.kind}")
    print(f"framework  : {flow.framework}")
    print(f"root       : {flow.root}")
    print(f"tools      : {', '.join(flow.tools)}")
    print(f"default    : {flow.default_tool}")
    print(f"stages     : {', '.join(flow_stages(flow))}")
    if catalog.tests:
        print("tests      : " + ", ".join(sorted(catalog.tests)))
    if catalog.groups:
        print("groups     : " + ", ".join(f"{name}={','.join(items)}" for name, items in sorted(catalog.groups.items())))


def selected_tool(flow: Flow, args: argparse.Namespace) -> str:
    tool = args.tool or flow.default_tool
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
            raise ConfigError(
                f"coverage replay requires an existing result.json: {result_path}"
            )
        return run_dir, None
    if existing.get("flow") != flow.name:
        raise ConfigError(
            f"{result_path}: flow is `{existing.get('flow')}`, expected `{flow.name}`"
        )
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


def _status_from_values(values: list[str]) -> str:
    for status in ("ERROR", "TIMEOUT", "FAIL", "UNKNOWN", "PASS"):
        if status in values:
            return status
    return "ERROR"


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
    new_stages = [
        stage for stage in current.get("stages", []) if isinstance(stage, dict)
    ]
    stages = [*old_stages, *new_stages]
    status = _status_from_values(
        [str(stage.get("status", "UNKNOWN")) for stage in stages]
    )
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
    previous = payload.get("coverage")
    merged = dict(previous) if isinstance(previous, dict) else {}
    merged.update(coverage)
    merged.update(
        {
            "requested": bool(coverage.get("enabled")),
            "overall_percent": coverage.get("total_percent"),
            "report_dir": coverage.get("report"),
            "summary_json": coverage.get("summary"),
        }
    )
    payload["coverage"] = merged
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


def selected_executor(flow: Flow, args: argparse.Namespace) -> str:
    scheduler = flow.raw.get("scheduler", {})
    if not isinstance(scheduler, dict):
        raise ConfigError(f"{flow.path}: [scheduler] must be a table")
    executor = args.executor or str(scheduler.get("default_executor", "local"))
    allowed = as_str_list(scheduler.get("allowed"), "scheduler.allowed")
    if allowed and executor not in allowed:
        raise ConfigError(f"executor `{executor}` is not allowed for flow `{flow.name}`")
    if executor != "local":
        raise ConfigError(f"executor `{executor}` is configured but non-local dispatch is not implemented")
    return executor


def validate_selected_tool_available(tool: str, simulators: dict[str, Any], args: argparse.Namespace) -> None:
    if args.dry_run:
        return
    cfg = simulators.get(tool, {})
    binary = str(cfg.get("binary", tool)) if isinstance(cfg, dict) else tool
    if shutil.which(binary):
        return
    raise ConfigError(
        f"selected tool `{tool}` requires `{binary}` in PATH. "
        f"Load the simulator environment or run `--doctor --tool {tool}` for details."
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
        requested = ["formal"] if flow.kind == "fv" and "formal" in available else ["sim" if "sim" in available else "regress"]
    elif args.regress:
        requested = [stage for stage in ("flist", "hdl_compile", "elaborate", "sim") if stage in available]
    elif flow.kind == "fv" and "formal" in available:
        requested = ["formal"]
    else:
        requested = [stage for stage in ("flist", "hdl_compile", "elaborate", "sim") if stage in available]

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


def select_by_tags(catalog: TestCatalog, candidates: list[str], tags: list[str]) -> list[str]:
    """Keep candidate test names whose tags intersect any of `tags`, preserving order."""
    wanted = set(tags)
    return [name for name in candidates
            if (test := catalog.tests.get(name)) is not None and wanted.intersection(test.tags)]


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


def scheduler_requested(args: argparse.Namespace, requested: list[str], items: list[str], catalog: TestCatalog) -> bool:
    if args.regress or args.reseed or args.retry or args.max_failures is not None:
        return True
    if args.stage and "regress" in args.stage:
        return True
    if any(name in catalog.groups for name in requested):
        return True
    return len(items) > 1


def validate_regression_seed_options(args: argparse.Namespace, randomize_regression_seeds: bool) -> None:
    if randomize_regression_seeds and args.seed is not None:
        raise ConfigError(
            "--seed cannot be used with regression mode; rerun an individual test "
            "with --stage sim --seed N"
        )


def sim_seed_plan(catalog: TestCatalog, sim_cfg: dict[str, Any], args: argparse.Namespace, item: str) -> list[int]:
    """Deterministic single-simulation seed priority: CLI, testlist, defaults."""
    return [seed_for_item(catalog, sim_cfg, args, item)]


def regression_reseed_count(catalog: TestCatalog, args: argparse.Namespace, item: str) -> int:
    test = catalog.tests.get(item)
    count = test.reseed if test and test.reseed is not None else (args.reseed if args.reseed is not None else 1)
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


def regression_seed_plan(catalog: TestCatalog, args: argparse.Namespace, item: str, seen_seeds: set[int]) -> list[int]:
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
        return regression_seed_plan(catalog, args, item, seen_seeds if seen_seeds is not None else set())
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
) -> tuple[dict[str, str], list[str]]:
    """Resolve a target per selected test and return first-seen unique target order."""
    if not items:
        target = default_target_name(sim_cfg)
        return {}, [target]

    target_by_item: dict[str, str] = {}
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        test = catalog.tests[item]
        target = resolved_target_name(sim_cfg, test)
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
    # the selected item even when simulation is intentionally omitted.
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
        ),
    )


def default_run_dir(dut_dv_root: Path, stamp: str, tool: str, label: str) -> Path:
    # Per-DUT run tree: <dut-dv-root>/build/runs/<stamp>__<tool>__<label>. The DUT dv root already
    # identifies the DUT, so runs/ adds no redundant <dut> layer (and no repo-root build/).
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
    simulators: dict[str, Any],
    policies: dict[str, Any],
    args: argparse.Namespace,
) -> int:
    replay_run_dir, existing_result = _existing_run_result(root, flow, args)
    tool = selected_tool(flow, args)
    executor = selected_executor(flow, args)
    validate_selected_tool_available(tool, simulators, args)
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
    stages = selected_stages(flow, args)
    need_items = any(stage_needs_item(stage) for stage in stages)
    requested: list[str] = []
    items: list[str] = []
    if need_items:
        if args.items:
            requested = list(args.items)
            items = expand_items(catalog, requested, need_items, allow_duplicates=args.allow_duplicates)
        elif args.tag:
            # Tag-only selection starts from the whole catalog (in definition order).
            items = list(catalog.tests)
        else:
            requested = requested_items(catalog, args)
            items = expand_items(catalog, requested, need_items, allow_duplicates=args.allow_duplicates)
        if args.tag:
            items = select_by_tags(catalog, items, args.tag)
            if not items:
                raise ConfigError(f"no tests match tag(s): {', '.join(args.tag)}")

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
    target_by_item, build_targets = target_plan(catalog, sim_cfg, items if need_items else [])
    if flow.kind == "fv":
        explicit_targets = [item for item in items if catalog.tests[item].target]
        if explicit_targets:
            raise ConfigError(
                "per-test `target` selection is supported for simulation flows only; "
                f"formal item(s) set target: {', '.join(explicit_targets)}"
            )
    else:
        validate_target_plan(sim_cfg, build_targets)
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

    console = Console(args.ui, quiet=args.quiet, verbose=args.verbose)
    args._ui_console = console
    args._ui_leaf_mode = "compact" if scheduler else "full"
    run_started = time.monotonic()
    results: list[StageResult] = []
    runs_by_item: dict[str, list[tuple[int, StageResult]]] = {}
    regression_jobs: list[dict[str, Any]] = []
    final_failures = 0

    def regression_job(
        stage: str,
        item: str,
        seed: int,
        attempt: int,
        result: StageResult,
        result_json: str | None = None,
    ) -> dict[str, Any]:
        return {
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

    def run_wave_debug_leaf(
        stage: str,
        item: str,
        seed: int,
        attempt: int,
        source_result: StageResult,
    ) -> tuple[StageResult, str | None]:
        log_path = repo_path(root, source_result.log) if source_result.log else None
        failure_time = find_failure_time_ps(log_path)
        debug_args = copy.copy(args)
        debug_args.waves = args.waves_on_fail
        debug_args.waves_on_fail = None
        debug_args.wave_retention = args.wave_retention or "failed"
        debug_args._wave_debug_rerun = True
        debug_args._wave_failure_time = failure_time
        debug_args._ui_leaf_mode = "compact" if scheduler else "full"
        console.event(
            "waves",
            f"rerun item={item} seed={seed} attempt={attempt} "
            f"format={resolve_wave_format(debug_args, simulators, tool)}",
        )
        debug_result = run_stage(
            flow,
            root,
            sim_cfg_for_item(item),
            catalog,
            stage,
            item,
            debug_args,
            tool,
            run_dir,
            simulators,
            policies,
            nest=True,
            attempt=attempt,
            seed_override=seed,
        )
        item_dir = item_artifact_dir(run_dir, item, seed=seed, attempt=attempt, nest=True)
        result_json = repo_rel(root, item_dir / "result.json")
        if not args.dry_run:
            write_result(
                item_dir / "result.json",
                fragment_payload(
                    flow=flow,
                    root=root,
                    tool=tool,
                    run_dir=run_dir,
                    item=item,
                    seed=seed,
                    result=debug_result,
                ),
            )
        return debug_result, result_json

    def run_leaf(stage: str, item: str, seed: int) -> tuple[str, int, StageResult, list[dict[str, Any]]]:
        attempt_results: list[StageResult] = []
        jobs: list[dict[str, Any]] = []
        for attempt in range((args.retry or 0) + 1):
            result = run_stage(
                flow,
                root,
                sim_cfg_for_item(item),
                catalog,
                stage,
                item,
                args,
                tool,
                run_dir,
                simulators,
                policies,
                nest=nest,
                attempt=attempt,
                seed_override=seed,
            )
            attempt_results.append(result)
            item_dir = item_artifact_dir(run_dir, item, seed=seed, attempt=attempt, nest=nest)
            result_json = repo_rel(root, item_dir / "result.json")
            jobs.append(regression_job(stage, item, seed, attempt, result, result_json))
            if not args.dry_run:
                write_result(
                    item_dir / "result.json",
                    fragment_payload(
                        flow=flow,
                        root=root,
                        tool=tool,
                        run_dir=run_dir,
                        item=item,
                        seed=seed,
                        result=result,
                    ),
                )
            if result.status == "PASS" or not scheduler:
                break
        final = attempt_results[-1]
        if (
            waves_on_fail_requested(args)
            and stage in {"sim", "regress"}
            and final.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
        ):
            debug_attempt = len(jobs)
            debug_result, debug_json = run_wave_debug_leaf(stage, item, seed, debug_attempt, final)
            debug_record = regression_job(stage, item, seed, debug_attempt, debug_result, debug_json)
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
        return item, seed, attempt_results[-1], jobs

    def record_leaf(item: str, seed: int, result: StageResult, jobs: list[dict[str, Any]]) -> bool:
        results.append(result)
        runs_by_item.setdefault(item, []).append((seed, result))
        regression_jobs.extend(jobs)
        return scheduler and result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}

    def needs_parallel_cocotb_prebuild(stage: str, target: str) -> bool:
        available = flow_stages(flow)
        sim_stage = available.get(stage)
        hdl_compile_stage = available.get("hdl_compile")
        elaborate_stage = available.get("elaborate")
        cocotb_build_defined = (
            (isinstance(hdl_compile_stage, dict) and str(hdl_compile_stage.get("kind", "")) == "cocotb_build")
            or (isinstance(elaborate_stage, dict) and str(elaborate_stage.get("kind", "")) == "cocotb_build")
        )
        return (
            stage in {"sim", "regress"}
            and isinstance(sim_stage, dict)
            and str(sim_stage.get("kind", "")) in {"cocotb_sim", "cocotb_verilator"}
            and cocotb_build_defined
            and target not in getattr(args, "_cocotb_prebuilt_targets", set())
        )

    try:
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
        for stage in stages:
            if stage in {"flist", "hdl_compile", "elaborate"}:
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
                if aggregate_status(results) in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}:
                    break
            elif stage in {"sim", "regress", "formal"}:
                seen_regression_seeds: set[int] = set()
                leaves = [
                    (item, seed)
                    for item in items
                    for seed in seed_plan(
                        catalog,
                        sim_cfg,
                        args,
                        item,
                        scheduler and stage in {"sim", "regress"},
                        seen_regression_seeds,
                    )
                ]
                leaf_item_width = max((len(item) for item, _ in leaves), default=44)
                leaf_seed_width = max((len(str(seed)) for _, seed in leaves), default=8)
                completed_leaves = 0
                parallel = (
                    scheduler
                    and args.sim_jobs > 1
                    and len(leaves) > 1
                    and args.max_failures is None
                    and not args.dry_run
                )
                if parallel:
                    missing_prebuilds = [
                        target for target in build_targets
                        if needs_parallel_cocotb_prebuild(stage, target)
                    ]
                    for target in missing_prebuilds:
                        prebuild_stage = "hdl_compile" if "hdl_compile" in flow_stages(flow) else "elaborate"
                        console.event("scheduler", f"pre-building cocotb model for target `{target}` before parallel sim")
                        prebuild = run_stage(
                            flow,
                            root,
                            target_cfgs[target],
                            catalog,
                            prebuild_stage,
                            None,
                            args,
                            tool,
                            run_dir,
                            simulators,
                            policies,
                            nest=nest,
                        )
                        results.append(prebuild)
                        if prebuild.status != "PASS":
                            break
                    if missing_prebuilds and aggregate_status(results) in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}:
                        break
                    console.regression_start(
                        total=len(leaves),
                        jobs=args.sim_jobs,
                        executor=executor,
                        seeds=regression_seed_label(leaves),
                        retry=args.retry or 0,
                        item_width=leaf_item_width,
                        seed_width=leaf_seed_width,
                    )
                    with ThreadPoolExecutor(max_workers=args.sim_jobs) as pool:
                        futures = {pool.submit(run_leaf, stage, item, seed): (item, seed) for item, seed in leaves}
                        for future in as_completed(futures):
                            item, seed, result, jobs = future.result()
                            failed = record_leaf(item, seed, result, jobs)
                            completed_leaves += 1
                            console.regression_leaf_done(
                                index=completed_leaves,
                                total=len(leaves),
                                item=item,
                                seed=seed,
                                attempt=max(0, len(jobs) - 1),
                                status=result.status,
                                duration_sec=result.duration_sec,
                                log=result.log,
                                reason=result.reason,
                                target=(result.target or target_by_item.get(item)) if multi_target else None,
                            )
                            if failed:
                                final_failures += 1
                else:
                    if scheduler:
                        console.regression_start(
                            total=len(leaves),
                            jobs=args.sim_jobs,
                            executor=executor,
                            seeds=regression_seed_label(leaves),
                            retry=args.retry or 0,
                            item_width=leaf_item_width,
                            seed_width=leaf_seed_width,
                        )
                    for item, seed in leaves:
                        if scheduler and args.max_failures is not None and final_failures >= args.max_failures:
                            skipped = StageResult(
                                stage=stage,
                                item=item,
                                status="SKIP",
                                return_code=0,
                                duration_sec=0.0,
                                started_at=datetime.now(UTC).isoformat(),
                                ended_at=datetime.now(UTC).isoformat(),
                                reason="skipped after --max-failures threshold",
                            )
                            results.append(skipped)
                            runs_by_item.setdefault(item, []).append((seed, skipped))
                            regression_jobs.append(regression_job(stage, item, seed, 0, skipped))
                            completed_leaves += 1
                            console.regression_leaf_done(
                                index=completed_leaves,
                                total=len(leaves),
                                item=item,
                                seed=seed,
                                attempt=0,
                                status=skipped.status,
                                duration_sec=skipped.duration_sec,
                                log=skipped.log,
                                reason=skipped.reason,
                                target=target_by_item.get(item) if multi_target else None,
                            )
                            continue

                        item, seed, result, jobs = run_leaf(stage, item, seed)
                        failed = record_leaf(item, seed, result, jobs)
                        if scheduler:
                            completed_leaves += 1
                            console.regression_leaf_done(
                                index=completed_leaves,
                                total=len(leaves),
                                item=item,
                                seed=seed,
                                attempt=max(0, len(jobs) - 1),
                                status=result.status,
                                duration_sec=result.duration_sec,
                                log=result.log,
                                reason=result.reason,
                                target=(result.target or target_by_item.get(item)) if multi_target else None,
                            )
                        if failed:
                            final_failures += 1
                            if args.max_failures is not None and final_failures >= args.max_failures:
                                console.event(
                                    "note",
                                    f"max failures reached ({args.max_failures}); remaining jobs will be skipped",
                                )
            else:
                if stage == "c_compile" and items:
                    for item in items:
                        item_cfg = sim_cfg_for_item(item)
                        seed = seed_for_item(catalog, item_cfg, args, item)
                        results.append(run_stage(flow, root, item_cfg, catalog, stage, item, args, tool, run_dir, simulators, policies, nest=nest, seed_override=seed))
                else:
                    results.append(run_stage(flow, root, sim_cfg, catalog, stage, None, args, tool, run_dir, simulators, policies, nest=nest))
            if not scheduler and aggregate_status(results) in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}:
                break

        # Per-test rollups across seeds/attempts. Only when nested: in a flat run the leaf fragment is
        # already the per-test `<test>/result.json`, so writing a rollup there would clobber it.
        if nest and not args.dry_run:
            for item, runs in runs_by_item.items():
                write_result(run_dir / item / "result.json", rollup_payload(flow=flow, root=root, tool=tool, run_dir=run_dir, item=item, runs=runs))
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
            )
        if scheduler:
            console.regression_summary(
                runs_by_item,
                ordered_items=items,
                elapsed_sec=time.monotonic() - run_started,
            )

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
        )
        if existing_result is not None and replay_run_dir == run_dir:
            payload = _merge_coverage_replay_result(existing_result, payload)
        result_path = run_dir / "result.json"
        if not args.dry_run:
            write_result(result_path, payload)
            if args.result:
                export_path = Path(args.result).expanduser()
                if not export_path.is_absolute():
                    export_path = root / export_path
                if export_path != result_path:
                    write_result(export_path, payload)
            if existing_result is not None and replay_run_dir == run_dir:
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
        )
        return exit_code_for_status(status)
    finally:
        console.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_mode_options(args)
        root = repo_root(Path(__file__))

        # Diagnostics report their own findings (and must not be pre-empted by the fail-fast
        # validate_all below), so dispatch them first.
        if args.validate_configs:
            return cmd_validate_configs(root)
        if args.doctor:
            return cmd_doctor(root, args)

        duts, simulators, policies, executors = validate_all(root)

        if args.list:
            if args.dut:
                flow = resolve_dut(root, args.dut, mode=args.mode)
                validate_flow(flow, root, simulators, policies, executors)
                list_flow_detail(flow, root)
            else:
                list_flows(duts)
            return 0

        if not args.dut:
            raise ConfigError("--dut is required unless --list, --validate-configs, or --doctor is used")
        if args.dut not in duts:
            raise ConfigError(f"unknown DUT `{args.dut}`")
        flow = resolve_dut(root, args.dut, mode=args.mode)
        validate_flow(flow, root, simulators, policies, executors)
        return run_flow(root=root, flow=flow, simulators=simulators, policies=policies, args=args)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
