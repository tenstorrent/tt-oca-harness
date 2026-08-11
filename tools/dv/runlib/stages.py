"""Stage execution for the native DV runner."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any

from .buildcache import (
    apply_option_env,
    build_fingerprint,
    build_options_cfg,
    build_verilator_cfg,
    build_vcs_cfg,
    build_xcelium_cfg,
    cache_key_extra,
    effective_build_jobs,
    option_build_args,
    resolve_build_dir,
    vcs_build_args,
    vcs_version,
    verilator_version,
    xcelium_build_args,
    xcelium_version,
)
from .compat import UTC
from .config import (
    as_int,
    as_str_list,
    build_cfg,
    c_build_cfg,
    cocotb_cfg,
    config_list,
    config_section,
    coverage_cfg,
    default_target_name,
    flow_stages,
    selected_compile_target,
    selected_run_mode,
    selected_run_target,
    sim_global_args,
    target_flags,
)
from .coverage import (
    CANONICAL_METRICS,
    CoverageError,
    artifact_ready,
    coverage_artifact_path,
    discover_coverage_inputs,
    load_manifest,
    new_manifest,
    parse_coverage_report,
    render_tokens,
    write_json,
)
from .coverage_parsers import parse_coverage_details
from .coverage_policy import (
    CoveragePolicy,
    apply_coverage_policy,
    load_coverage_policy,
    native_policy_args,
    native_policy_manifest,
)
from .logparse import parse_stage_result
from .models import ConfigError, Flow, StageResult, StageTimeoutError, TestCatalog, TestEntry
from .paths import repo_path, repo_rel
from .ui import Console
from .waves import (
    build_wave_metadata,
    format_time_ps,
    resolve_wave_format,
    wave_active,
    wave_time_range,
)

# Default bucket when a stage's process fails for an unclassified reason. Cause-based buckets
# (config_error for ConfigError, timeout for StageTimeoutError) override these in run_stage —
# a cov_merge tool crash is a tool_error, never a coverage_threshold miss.
FAILURE_BUCKET_BY_STAGE = {
    "flist": "config_error",
    "hdl_compile": "compile_error",
    "c_compile": "compile_error",
    "elaborate": "elaboration_error",
    "sim": "sim_failure",
    "regress": "sim_failure",
    "cov_merge": "tool_error",
    "cov_report": "tool_error",
    "formal": "formal_fail",
    "clean": "tool_error",
}

# Env snapshots are run artifacts that may be published (dashboards, CI uploads). Redact values of
# variables that commonly carry secrets or license-server endpoints so they never leak.
REDACTED_ENV_PATTERN = re.compile(
    r"LICENSE|LM_LICENSE|SNPSLMD|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_KEY|AUTH",
    re.IGNORECASE,
)
REDACTED_VALUE = "<redacted>"


def render_text(text: str, ctx: dict[str, str]) -> str:
    rendered = text
    for key, value in ctx.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def required_path(cfg: dict[str, Any], key: str, section: str, where: str) -> str:
    """Return a required build-output path from `cfg`, or fail loud.

    Build/run output directories are per-DUT policy and must be declared in the flow's sim_cfg;
    the runner never invents one. Mirrors the existing ``[build].top_module`` requirement so a
    missing path is a config error, not a silent fallback to a runner-owned default.
    """
    value = cfg.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: [{section}].{key} is required and must be a non-empty string (declare it in your sim_cfg)")
    return value.strip()


def _target_name(sim_cfg: dict[str, Any]) -> str:
    return default_target_name(sim_cfg)


def _target_fingerprint_extra(target_name: str, target: dict[str, Any]) -> list[str]:
    return [
        f"target={target_name}",
        "target_cfg=" + json.dumps(target, sort_keys=True, separators=(",", ":")),
    ]


def _build_jobs_arg(args: argparse.Namespace) -> int:
    return int(getattr(args, "build_jobs", None) or args.sim_jobs)


def _verilator_public_scope_fingerprint(root: Path, build: dict[str, Any]) -> list[str]:
    scope = str(build_verilator_cfg(build).get("public_scope") or "").strip()
    if not scope:
        return []
    path = repo_path(root, scope)
    text = (
        path.read_text(encoding="utf-8", errors="replace")
        if path.is_file()
        else "<missing>"
    )
    return [f"verilator_public_scope={scope}", "verilator_public_scope_text=" + text]


def _prebuilt_targets(args: argparse.Namespace) -> set[str]:
    targets = getattr(args, "_cocotb_prebuilt_targets", None)
    if not isinstance(targets, set):
        targets = set()
        setattr(args, "_cocotb_prebuilt_targets", targets)
    return targets


def _mark_cocotb_prebuilt(args: argparse.Namespace, target_name: str) -> None:
    _prebuilt_targets(args).add(target_name)


def _is_cocotb_prebuilt(args: argparse.Namespace, target_name: str) -> bool:
    return target_name in _prebuilt_targets(args)


def _target_build_metadata(
    *,
    target_name: str,
    tool: str,
    build_dir: Path,
    fingerprint: str | None = None,
    status: str | None = None,
    executor: str = "local",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "target": target_name,
        "tool": tool,
        "build_dir": str(build_dir),
        "artifact": str(build_dir),
        "executor": executor,
    }
    if fingerprint:
        metadata["fingerprint"] = fingerprint
    if status:
        metadata["status"] = status
    return metadata


def _cocotb_target_build_metadata(info: dict[str, Any], tool: str, *, status: str | None = None) -> dict[str, Any]:
    return _target_build_metadata(
        target_name=str(info["target_name"]),
        tool=tool,
        build_dir=info["sim_build"],
        fingerprint=str(info.get("fingerprint", "")) or None,
        status=status,
    )


def _wave_format(args: argparse.Namespace, tool: str) -> str:
    if not wave_active(args):
        return ""
    simulators = getattr(args, "_simulators", {})
    return resolve_wave_format(args, simulators, tool)


def _wave_range(args: argparse.Namespace) -> dict[str, Any]:
    failure_info = getattr(args, "_wave_failure_time", {})
    failure_time_ps = failure_info.get("time_ps") if isinstance(failure_info, dict) else None
    return wave_time_range(args, failure_time_ps=failure_time_ps)


def _backend_range_supported(tool: str, wave_format: str) -> bool:
    if tool == "xcelium" and wave_format == "shm":
        return True
    if tool == "vcs" and wave_format == "fsdb":
        return True
    return False


def _xcelium_wave_tcl(
    *,
    tcl_path: Path,
    waves_dir: Path,
    item: str,
    wave_format: str,
    range_info: dict[str, Any],
    dry_run: bool,
) -> None:
    db_path = waves_dir / (f"{item}.shm" if wave_format == "shm" else f"{item}.{wave_format}")
    start_ps = range_info.get("start_ps")
    end_ps = range_info.get("end_ps")
    lines = [
        "# Generated by run_dv.py for waveform capture.",
    ]
    if start_ps is not None and start_ps > 0:
        lines.append(f"run {format_time_ps(start_ps)}")
    lines.extend([
        f"database -open waves -into {db_path} -event -default",
        "probe -create [scope -tops] -all -depth to_cells -database waves",
    ])
    if end_ps is not None:
        duration = max(0, int(end_ps) - int(start_ps or 0))
        if duration > 0:
            lines.append(f"run {format_time_ps(duration)}")
        lines.append("database -close waves")
        lines.append("run")
    else:
        lines.append("run")
    lines.append("exit")
    write_text_file(tcl_path, "\n".join(lines) + "\n", dry_run)


def item_artifact_dir(run_dir: Path, item: str, *, seed: int | None = None, attempt: int = 0, nest: bool = False) -> Path:
    """Per-test (test-major) artifact directory.

    Single-test invocations stay flat at ``<run_dir>/<item>``. Regression/group runs always nest
    every test as ``<run_dir>/<item>/seed_<seed>/attempt_<attempt>`` so the layout is uniform.
    """
    base = run_dir / item
    if nest:
        base = base / f"seed_{seed}" / f"attempt_{attempt}"
    return base


def artifact_root(run_dir: Path, stage: str, item: str | None = None, *, seed: int | None = None, attempt: int = 0, nest: bool = False) -> Path:
    """Run-shared stages live under ``stages/<stage>/``; per-test stages are test-major."""
    if item is None:
        return run_dir / "stages" / stage
    return item_artifact_dir(run_dir, item, seed=seed, attempt=attempt, nest=nest)


def seed_for_item(catalog: TestCatalog, sim_cfg: dict[str, Any], args: argparse.Namespace, item: str) -> int:
    if args.seed is not None:
        return int(args.seed)
    test = catalog.tests.get(item)
    if test and test.seed is not None:
        return int(test.seed)
    default_seed = sim_cfg.get("defaults", {}).get("seed", 1)
    return int(default_seed)


def resolve_timeout_sec(
    sim_cfg: dict[str, Any],
    test: TestEntry | None,
    run_mode: dict[str, Any],
    args: argparse.Namespace,
) -> int | None:
    """Timeout precedence: CLI --timeout, then the test entry, then run mode, then [defaults]."""
    if args.timeout is not None:
        return int(args.timeout)
    if test is not None and test.timeout_sec:
        return int(test.timeout_sec)
    value = as_int(run_mode.get("timeout_sec"), "run_mode.timeout_sec")
    if value:
        return value
    value = as_int(sim_cfg.get("defaults", {}).get("timeout_sec"), "defaults.timeout_sec")
    return value or None


@contextmanager
def watchdog_timeout(timeout_sec: int | None, label: str):
    """Bound an in-process blocking call (the cocotb Python runner) by wall-clock time.

    SIGALRM fires in the main thread, which is exactly where the runner blocks while the simulator
    runs as a direct child process; on expiry the direct children are reaped before raising so a
    hung simulator cannot outlive the runner.
    """
    # Parallel regression workers run in Python threads. Python only permits
    # signal.signal() from the main interpreter thread, so threaded cocotb runs
    # cannot use this in-process SIGALRM guard.
    if (
        not timeout_sec
        or os.name == "nt"
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def on_alarm(signum: int, frame: Any) -> None:
        subprocess.run(["pkill", "-P", str(os.getpid())], check=False)
        raise StageTimeoutError(f"{label} exceeded timeout of {timeout_sec}s")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(int(timeout_sec))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def write_text_file(path: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        print(f"WRITE: {path}", flush=True)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def write_script(path: Path, root: Path, argv: list[str], dry_run: bool) -> None:
    body = "#!/usr/bin/env bash\nset -euo pipefail\n"
    body += "cd " + shlex.quote(str(root)) + "\n"
    body += " ".join(shlex.quote(part) for part in argv) + "\n"
    write_text_file(path, body, dry_run)
    if not dry_run:
        path.chmod(0o755)


def write_env_snapshot(path: Path, env: dict[str, str], dry_run: bool) -> None:
    lines = [
        f"{key}={REDACTED_VALUE if REDACTED_ENV_PATTERN.search(key) else shlex.quote(value)}"
        for key, value in sorted(env.items())
    ]
    write_text_file(path, "\n".join(lines) + "\n", dry_run)


@contextmanager
def scoped_environ(env: dict[str, str]):
    """Temporarily replace this process environment for in-process tool runners."""
    old_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@contextmanager
def redirect_process_output(handle: Any):
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    try:
        os.dup2(handle.fileno(), 1)
        os.dup2(handle.fileno(), 2)
        yield
    finally:
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)


@contextmanager
def tee_process_output(handle: Any):
    """Mirror process-level stdout/stderr to both the terminal and a log file."""
    sys.stdout.flush()
    sys.stderr.flush()
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    terminal_fd = os.dup(stdout_fd)
    read_fd, write_fd = os.pipe()

    def pump() -> None:
        with os.fdopen(read_fd, "rb", closefd=True) as reader:
            while True:
                data = reader.read(8192)
                if not data:
                    break
                os.write(terminal_fd, data)
                handle.write(data.decode(errors="replace"))
                handle.flush()

    thread = threading.Thread(target=pump, name="dv-output-tee", daemon=True)
    thread.start()
    try:
        os.dup2(write_fd, 1)
        os.dup2(write_fd, 2)
        os.close(write_fd)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)
        thread.join()
        os.close(terminal_fd)


@contextmanager
def capture_process_output(handle: Any, quiet: bool):
    if quiet:
        with redirect_process_output(handle):
            yield
    else:
        with tee_process_output(handle):
            yield


@contextmanager
def backend_output(handle: Any, *, quiet: bool, verbose: bool):
    if verbose and not quiet:
        with tee_process_output(handle):
            yield
    else:
        with redirect_stdout(handle), redirect_stderr(handle), redirect_process_output(handle):
            yield


def console_from_args(args: argparse.Namespace) -> Console:
    console = getattr(args, "_ui_console", None)
    if console is not None:
        return console
    return Console(getattr(args, "ui", "auto"), quiet=getattr(args, "quiet", False), verbose=getattr(args, "verbose", False))


def compact_leaf_ui(args: argparse.Namespace, stage_name: str, item: str | None) -> bool:
    return (
        getattr(args, "_ui_leaf_mode", "") == "compact"
        and stage_name in {"sim", "regress"}
        and item is not None
        and not getattr(args, "verbose", False)
    )


@contextmanager
def progress_step(console: Console, label: str, quiet: bool, interval_sec: int = 30):
    """Print periodic progress for long cocotb runner calls that can be silent."""
    if quiet:
        yield
        return

    if console.verbose:
        console.step_start(label)
        yield
        return

    start = time.monotonic()
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(interval_sec):
            elapsed = int(time.monotonic() - start)
            console.step_heartbeat(label, elapsed)

    console.step_start(label)
    thread = threading.Thread(target=heartbeat, name="dv-progress-heartbeat", daemon=True)
    thread.start()
    failed = False
    try:
        yield
    except Exception:
        failed = True
        raise
    finally:
        stop.set()
        thread.join()
        elapsed = time.monotonic() - start
        if failed:
            console.step_failed(label, elapsed)
        else:
            console.step_done(label, elapsed)


def run_subprocess(
    argv: list[str],
    root: Path,
    log_path: Path,
    dry_run: bool,
    script_path: Path,
    env_path: Path,
    quiet: bool,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    verbose: bool = False,
    timeout_sec: int | None = None,
) -> int:
    workdir = cwd or root
    if dry_run or verbose:
        print("CMD  : " + " ".join(shlex.quote(part) for part in argv), flush=True)
    write_script(script_path, workdir, argv, dry_run)
    write_env_snapshot(env_path, env or dict(os.environ), dry_run)
    if dry_run:
        return 0
    workdir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def terminate_process_group(proc: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The direct child may exit on SIGTERM while grandchildren in its session keep running.
        # A final group kill makes timeout/Ctrl-C cleanup deterministic for tool wrappers.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    with log_path.open("w", encoding="utf-8") as log:
        log.write("# cmd: " + " ".join(shlex.quote(part) for part in argv) + "\n")
        log.flush()
        proc = subprocess.Popen(
            argv,
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        start = time.monotonic()
        timed_out = False
        try:
            while True:
                if timeout_sec is not None and time.monotonic() - start > timeout_sec:
                    timed_out = True
                    break
                events = selector.select(timeout=0.2)
                for key, _mask in events:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        break
                    text = chunk.decode(errors="replace")
                    log.write(text)
                    log.flush()
                    if verbose and not quiet:
                        print(text, end="", flush=True)
                if proc.poll() is not None and not selector.get_map():
                    break
        except BaseException:
            terminate_process_group(proc)
            raise
        finally:
            selector.close()
        if timed_out:
            terminate_process_group(proc)
            log.write(f"\n# TIMEOUT: command exceeded {timeout_sec}s and was killed\n")
            log.flush()
            raise StageTimeoutError(
                f"`{argv[0]}` exceeded timeout of {timeout_sec}s"
            )
        return proc.returncode


def get_cocotb_runner():
    try:
        from cocotb.runner import get_runner

        return get_runner
    except ImportError:
        pass

    try:
        from cocotb_tools.runner import get_runner

        return get_runner
    except ImportError as exc:
        raise ConfigError(
            "cocotb runner support is required for cocotb_verilator stages. "
            "Launch via `python3 tools/dv/run_dv.py` so the uv-managed DV environment "
            f"provides cocotb (current interpreter: {sys.executable})"
        ) from exc


@contextmanager
def cocotb_make_jobs(jobs: int):
    """Temporary WA: map runlib build jobs onto cocotb runner's generated-model make.

    cocotb's Python runner hardcodes its generated Verilator model build through
    MAX_PARALLEL_BUILD_JOBS (default 4) and does not currently expose a
    per-build jobs argument. Keep the user-visible policy in config/CLI
    (`[build.options].build_jobs` / `--build-jobs`) and adapt that value here until
    cocotb grows a supported build_jobs API.
    """
    patched: list[tuple[Any, int]] = []
    if jobs > 1:
        for module_name in ("cocotb.runner", "cocotb_tools.runner"):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            if hasattr(module, "MAX_PARALLEL_BUILD_JOBS"):
                old_value = int(getattr(module, "MAX_PARALLEL_BUILD_JOBS"))
                setattr(module, "MAX_PARALLEL_BUILD_JOBS", jobs)
                patched.append((module, old_value))
    try:
        yield
    finally:
        for module, old_value in patched:
            setattr(module, "MAX_PARALLEL_BUILD_JOBS", old_value)


@contextmanager
def cocotb_public_scope(vlt_path: str):
    """Replace cocotb's global ``--public-flat-rw`` with a scoped Verilator public config.

    cocotb's Verilator runner hardcodes ``--public-flat-rw`` in its model build,
    marking every signal in the design public so cocotb can read/write any of them.
    For a large DUT (SEP) that is toxic: with everything public, Verilator must
    preserve the full internal structure and can no longer apply the ``split_var``
    hints already present in the AXI/common-cells RTL (rr_arb_tree, lzc, axi_demux).
    The false combinational ready/valid loops then cannot be split, so Verilator
    schedules hundreds of fake SCCs and a multi-million-entry input-combinational
    (ICO) settle region, and the model wedges or crawls.

    cocotb only needs the testbench top public (its root handle plus top-level ports
    such as clocks/reset/the AXI bus); internal probes/splices are implemented SV-side
    in tb_top. So we drop the global flag and add a scoped config that exposes only the
    tb top, leaving the DUT fabric optimisable. Measured on SEP: SCCs ~951 -> ~61, ICO
    Input region ~3.2M -> ~160K, and the smoke test runs to completion instead of
    wedging at the timeout.

    This wraps ``Verilator._build_command`` at runtime rather than editing the
    generated ``cocotb_tools/runner.py`` in the venv, which ``sim/run.sh`` recreates.
    """
    if not vlt_path:
        yield
        return
    if not Path(vlt_path).is_file():
        raise ConfigError(f"configured Verilator public_scope file does not exist: {vlt_path}")
    patched: list[tuple[Any, Any]] = []
    for module_name in ("cocotb.runner", "cocotb_tools.runner"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        cls = getattr(module, "Verilator", None)
        original = getattr(cls, "_build_command", None)
        if cls is None or original is None:
            continue

        def make_wrapper(orig: Any, vlt: str) -> Any:
            def _build_command(self: Any) -> Any:
                scoped = []
                for cmd in orig(self):
                    if not isinstance(cmd, (list, tuple)):
                        scoped.append(cmd)
                        continue
                    toks = [tok for tok in cmd if tok != "--public-flat-rw"]
                    # The Verilator invocation carries --vpi; inject the scoped config
                    # there (Verilator reads a .vlt by file extension). The `make` step
                    # has neither token and is left untouched.
                    if "--vpi" in toks and vlt not in toks:
                        toks.insert(toks.index("--vpi") + 1, vlt)
                    scoped.append(toks)
                return scoped

            return _build_command

        cls._build_command = make_wrapper(original, vlt_path)
        patched.append((cls, original))
    if not patched:
        raise ConfigError("configured Verilator public_scope but no cocotb Verilator runner was patched")
    try:
        yield
    finally:
        for cls, original in patched:
            cls._build_command = original


def generate_filelist(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    dry_run: bool,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    quiet: bool,
    verbose: bool = False,
    tool: str | None = None,
) -> int:
    build = build_cfg(flow, sim_cfg)
    bender_out = repo_path(root, str(build.get("bender_filelist", "")))
    combined_out = repo_path(root, str(build.get("filelist", "")))
    common_targets = as_str_list(build.get("common_bender_targets"), "build.common_bender_targets")
    targets = as_str_list(build.get("bender_targets"), "build.bender_targets")
    target_args: list[str] = []
    for target in [*common_targets, *targets]:
        target_args.extend(["-t", target])

    # FIXME(transition): drop licensed-IP wrappers the bender graph pulls in this sandbox (e.g.
    # SEP's Cadence sep_cdns_spi_wrap). Remove `build.exclude_files` support once those sources are
    # absent from the OSS checkout upstream.
    exclude_files = as_str_list(build.get("exclude_files"), "build.exclude_files")

    checkout_cmd = ["bender", "checkout"]
    flist_cmd = ["bender", "script", "flist-plus", *target_args]
    if dry_run or verbose:
        print("CMD  : " + " ".join(shlex.quote(part) for part in checkout_cmd), flush=True)
        print("CMD  : " + " ".join(shlex.quote(part) for part in flist_cmd) + f" > {bender_out}", flush=True)
        if exclude_files:
            print("NOTE : drop from filelist (build.exclude_files): " + ", ".join(exclude_files), flush=True)

    script_body = "#!/usr/bin/env bash\nset -euo pipefail\n"
    script_body += "cd " + shlex.quote(str(root)) + "\n"
    script_body += " ".join(shlex.quote(part) for part in checkout_cmd) + "\n"
    script_body += " ".join(shlex.quote(part) for part in flist_cmd) + " > " + shlex.quote(str(bender_out)) + "\n"
    write_text_file(script_path, script_body, dry_run)
    write_env_snapshot(env_path, os.environ, dry_run)
    if not dry_run:
        script_path.chmod(0o755)
        bender_out.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            log.write("# cmd: " + " ".join(shlex.quote(part) for part in checkout_cmd) + "\n")
            proc = subprocess.run(checkout_cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            log.write(proc.stdout)
            if verbose and not quiet:
                print(proc.stdout, end="")
            if proc.returncode:
                return proc.returncode

            log.write("# cmd: " + " ".join(shlex.quote(part) for part in flist_cmd) + f" > {bender_out}\n")
            with bender_out.open("w", encoding="utf-8") as handle:
                proc = subprocess.run(flist_cmd, cwd=root, stdout=handle, stderr=subprocess.PIPE, text=True)
            log.write(proc.stderr)
            if verbose and not quiet:
                print(proc.stderr, end="")
            if proc.returncode:
                return proc.returncode

            # Drop the licensed-IP wrappers named in build.exclude_files from the generated bender
            # filelist before it feeds the compile (see the FIXME above; substring match per line).
            if exclude_files and bender_out.exists():
                kept: list[str] = []
                for line in bender_out.read_text(encoding="utf-8").splitlines():
                    if any(pat in line for pat in exclude_files):
                        log.write(f"# excluded (build.exclude_files): {line}\n")
                    else:
                        kept.append(line)
                bender_out.write_text("\n".join(kept) + "\n", encoding="utf-8")

    incdirs = [repo_path(root, value) for value in as_str_list(build.get("incdirs"), "build.incdirs")]
    # `stubs` are DUT-local OVERRIDE sources that replace the real RTL for a module. `sources` are
    # ADDITIVE tb components (e.g. SEP's mem responders) that may reference DUT package types, so they
    # go AFTER the bender filelist where those packages are already declared.
    # FIXME(transition): `stubs` is a transitional alias kept for DTP/SMC/SEP; remove it (and the
    # `build.exclude_files` filter above) once the licensed/non-Verilator sources are gone upstream.
    stubs = [repo_path(root, value) for value in as_str_list(build.get("stubs"), "build.stubs")]
    sources = [repo_path(root, value) for value in as_str_list(build.get("sources"), "build.sources")]

    # Stub selection/placement is tool-dependent, because "which duplicate module definition wins"
    # differs and because some stubs shadow real RTL that IS present in the bender graph:
    #   * Verilator (-Wno-MODDUP, FIRST-wins): keep ALL stubs and emit them BEFORE the bender
    #     filelist so they override the real RTL. The stubs exist to dodge Verilator RTL-codegen
    #     defects (e.g. PeakRDL nested structs in smc_reset_unit), so they MUST win here.
    #   * VCS (LAST-wins): a stub that also has real RTL in the bender graph would OVERRIDE it, and
    #     the checked-in stubs can lag the real port list (e.g. smc_reset_unit gained test_en_i /
    #     scan_rst_ni / rst_warm_smc_clk_no) -> a stale stub silently binds and elaboration fails
    #     with undefined-port errors. So for VCS keep ONLY the stubs that have NO real counterpart in
    #     the bender graph (OSS-absent modules like smc_dft_ctrl_status_wrap) and emit them AFTER the
    #     bender filelist, where the DUT packages they reference are already declared. Everything with
    #     real RTL is compiled from the bender graph instead.
    # A real counterpart is detected by matching the stub's file basename against the bender sources
    # (repo convention: one module per file, file named after the module).
    stubs_after = False
    if tool == "vcs" and stubs and bender_out and bender_out.exists():
        bender_basenames = {
            Path(line.strip()).name
            for line in bender_out.read_text(encoding="utf-8").splitlines()
            if line.strip().endswith(".sv")
        }
        stubs = [stub for stub in stubs if Path(stub).name not in bender_basenames]
        stubs_after = True

    lines = [f"+incdir+{path}" for path in incdirs]
    if not stubs_after:
        lines.extend(str(path) for path in stubs)
    if bender_out:
        lines.append(f"-f {bender_out}")
    if stubs_after:
        lines.extend(str(path) for path in stubs)
    lines.extend(str(path) for path in sources)
    if build.get("top_file"):
        lines.append(str(repo_path(root, str(build["top_file"]))))
    lines.append("")
    if dry_run:
        print(f"WRITE: {combined_out}", flush=True)
    if not dry_run:
        combined_out.parent.mkdir(parents=True, exist_ok=True)
        combined_out.write_text("\n".join(lines), encoding="utf-8")
    return 0


def verilator_compile(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    stage_name: str,
    tool: str,
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
    build = build_cfg(flow, sim_cfg)
    verilator_cfg = build_verilator_cfg(build)
    stage = flow_stages(flow)[stage_name]
    tool_cfg = stage.get(tool, {}) if isinstance(stage.get(tool, {}), dict) else {}
    compile_target = selected_compile_target(sim_cfg)
    work_dir = required_path(build, "work_dir", "build", str(flow.path))
    mdir = repo_path(root, str(tool_cfg.get("mdir", work_dir)))
    argv = ["verilator", "--cc"]
    argv.extend(as_str_list(verilator_cfg.get("compile_args"), "build.verilator.compile_args") or ["--timing", "-sv", "--language", "1800-2023"])
    if build.get("top_module"):
        argv.extend(["--top-module", str(build["top_module"])])
    argv.extend(target_flags(compile_target, "verilator"))
    argv.extend(args.comp_arg or [])
    argv.extend(f"+define+{define}" for define in config_list(compile_target, "defines"))
    argv.extend(f"+define+{define}" for define in (args.define or []))
    argv.extend(["-Mdir", str(mdir)])
    argv.extend(["-f", str(repo_path(root, str(build.get("filelist", ""))))])
    wave_format = _wave_format(args, tool)
    if wave_format:
        argv.append("--trace-fst" if wave_format == "fst" else "--trace")
    if not args.dry_run:
        mdir.mkdir(parents=True, exist_ok=True)
    options = build_options_cfg(build)
    env = apply_option_env(options, dict(os.environ), verilator_cfg)
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        env=env,
        verbose=args.verbose,
        timeout_sec=args.timeout,
    )


# cocotb is the single test framework across simulators. Use the Python runner for tools it
# supports well, and use cocotb's classic Makefile flow for VCS because cocotb.runner has no VCS
# backend in cocotb 1.9.x.
COCOTB_RUNNER_TOOLS = {"verilator", "xcelium"}
COCOTB_MAKE_TOOLS = {"vcs"}


def _cocotb_build_args(tool: str, flow: Flow, root: Path, build: dict[str, Any], run_target: dict[str, Any], compile_target: dict[str, Any], options: dict[str, Any], filelist: Path, args: argparse.Namespace) -> list[str]:
    defines = [f"+define+{d}" for d in (config_list(run_target, "defines") or config_list(compile_target, "defines"))]
    defines += [f"+define+{d}" for d in (args.define or [])]
    if tool == "verilator":
        verilator_cfg = build_verilator_cfg(build)
        return [
            *(as_str_list(verilator_cfg.get("compile_args"), "build.verilator.compile_args") or ["--timing", "-sv", "--language", "1800-2023"]),
            *target_flags(run_target, "verilator"),
            *(args.comp_arg or []),
            *defines,
            *option_build_args(options, verilator_cfg, _build_jobs_arg(args)),
            "-f",
            str(filelist),
        ]
    if tool == "vcs":
        return [
            "-f",
            str(filelist),
            *defines,
            *(target_flags(run_target, "vcs") or target_flags(compile_target, "vcs")),
            *(args.comp_arg or []),
        ]
    # xcelium: cocotb's runner loads its VPI and sets -access automatically; we add sources + knobs.
    xcelium_cfg = build_xcelium_cfg(build)
    timescale = str(xcelium_cfg.get("timescale", "")).strip()
    return [
        "-sv",
        *(["-timescale", timescale] if timescale else []),
        *(target_flags(run_target, "xcelium") or target_flags(compile_target, "xcelium")),
        *(args.comp_arg or []),
        *defines,
        *xcelium_build_args(options, xcelium_cfg, _build_jobs_arg(args)),
        "-f",
        str(filelist),
    ]


def _render_list(values: list[str], ctx: dict[str, str]) -> list[str]:
    return [render_text(value, ctx) for value in values]


def _render_run_test_args(
    run_mode: dict[str, Any],
    test: TestEntry,
    seed: int,
    repo_root: Path | str | None = None,
) -> list[str]:
    """Render `run_mode.args` + `test.args` with a seed/repo_root ctx so a
    testlist entry can template the per-leaf regression seed (e.g.
    `+sep_efuse_prog_fail_seed={seed}`) and portable asset paths (e.g.
    `+smc_efuse_hex={repo_root}/hw/sys/smc/dv/assets/smc_efuse_default.hex`).
    Only these two config-owned lists are templated; `sim_global_args`,
    `--sim-arg`, and `--plusarg` stay literal. Applied at every sim site so
    `{seed}` / `{repo_root}` behave identically across tools."""
    ctx = {"seed": str(seed)}
    if repo_root is not None:
        ctx["repo_root"] = str(repo_root)
    return [
        *_render_list(as_str_list(run_mode.get("args"), "run_mode.args"), ctx),
        *_render_list(list(test.args or []), ctx),
    ]


def _firmware_target(test: TestEntry | None, item: str | None) -> str:
    if test is None:
        return item or "default"
    firmware = test.firmware
    if isinstance(firmware, dict) and isinstance(firmware.get("name"), str):
        return str(firmware["name"])
    if isinstance(firmware, str) and firmware:
        return Path(firmware).name
    return test.name


def _stage_firmware_outputs(
    root: Path,
    sim_cfg: dict[str, Any],
    test: TestEntry,
    item_dir: Path,
) -> None:
    """Copy declared firmware outputs into the per-test simulation directory.

    Time-zero ROM/TCM models cannot wait for Python test code to copy images.
    The c_compile outputs are therefore the authoritative staging manifest for
    both full runs and later sim-only reruns.
    """
    if test.firmware is None:
        return
    mode = "default"
    if isinstance(test.firmware, dict):
        mode = str(test.firmware.get("mode", mode))
    template = c_build_cfg(sim_cfg).get(mode)
    if not isinstance(template, dict):
        raise ConfigError(f"missing [c_build.{mode}] template for `{test.name}`")
    fw_target = _firmware_target(test, test.name)
    ctx = {
        "flow": str(sim_cfg.get("name", "")),
        "tool": "",
        "item": test.name,
        "seed": "",
        "run_dir": str(item_dir.parent),
        "repo_root": str(root),
        "fw_target": fw_target,
        "build_dir": str(item_dir / "firmware"),
    }
    outputs = [
        repo_path(root, render_text(value, ctx))
        for value in as_str_list(template.get("outputs"), f"c_build.{mode}.outputs")
    ]
    missing = [path for path in outputs if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise ConfigError(
            f"firmware outputs missing for `{test.name}`; run c_compile first: {rendered}"
        )
    item_dir.mkdir(parents=True, exist_ok=True)
    for source in outputs:
        destination = item_dir / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)


def c_compile_stage(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str | None,
    args: argparse.Namespace,
    tool: str,
    stage_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    seed: int,
) -> int:
    test = catalog.tests.get(item) if item else None
    if item and test is None:
        raise ConfigError(f"unknown c_compile item `{item}`")
    if item and test is not None and test.firmware is None:
        if not args.dry_run:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8") as log:
                log.write(f"# c_compile skipped: `{item}` has no firmware entry\n")
            payload = {
                "schema_version": 1,
                "flow": flow.name,
                "item": item,
                "firmware_target": None,
                "mode": "none",
                "phase": "pre_sim",
                "cwd": ".",
                "argv": [],
                "outputs": [],
                "status": "SKIP",
                "reason": "test has no firmware entry",
            }
            (stage_dir / "c_compile.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return 0
    c_build = c_build_cfg(sim_cfg)
    if not c_build:
        raise ConfigError(
            f"{flow.path}: c_compile requested but no [c_build.<mode>] templates are defined"
        )
    mode = "default"
    if isinstance(test and test.firmware, dict):
        mode = str(test.firmware.get("mode", mode))
    template = c_build.get(mode)
    if not isinstance(template, dict):
        raise ConfigError(f"{flow.path}: missing [c_build.{mode}] template")

    fw_target = _firmware_target(test, item)
    build_dir = stage_dir / fw_target
    ctx = {
        "flow": flow.name,
        "tool": tool,
        "item": item or "",
        "seed": str(seed),
        "run_dir": str(stage_dir.parent.parent),
        "repo_root": str(root),
        "fw_target": fw_target,
        "build_dir": str(build_dir),
    }
    cwd_text = str(template.get("cwd", "."))
    cwd = repo_path(root, render_text(cwd_text, ctx))
    argv = _render_list(as_str_list(template.get("argv"), f"c_build.{mode}.argv"), ctx)
    if not argv:
        raise ConfigError(f"{flow.path}: [c_build.{mode}].argv must not be empty")
    argv += args.c_arg or []

    outputs = [
        repo_path(root, render_text(value, ctx))
        for value in as_str_list(template.get("outputs"), f"c_build.{mode}.outputs")
    ]
    # `--rebuild` (or `[build.options].rebuild`) forces a clean firmware build: drop the declared
    # outputs first so an incremental build tool (e.g. make) cannot skip up-to-date objects.
    build_options = config_section(config_section(sim_cfg, "build"), "options")
    if (bool(getattr(args, "rebuild", False)) or bool(build_options.get("rebuild", False))) and not args.dry_run:
        for path in outputs:
            if path.is_file():
                path.unlink()

    console = console_from_args(args)
    console.artifact("c_build", build_dir)
    rc = run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=cwd,
        verbose=args.verbose,
        timeout_sec=args.timeout,
    )

    missing = [path for path in outputs if not path.exists()]
    if rc == 0 and missing and not args.dry_run:
        with log_path.open("a", encoding="utf-8") as log:
            for path in missing:
                log.write(f"# MISSING OUTPUT: {path}\n")
        return 1

    if not args.dry_run:
        payload = {
            "schema_version": 1,
            "flow": flow.name,
            "item": item,
            "firmware_target": fw_target,
            "mode": mode,
            "phase": str(template.get("phase", "pre_sim")),
            "cwd": repo_rel(root, cwd),
            "argv": argv,
            "outputs": [repo_rel(root, path) for path in outputs],
            "status": "PASS" if rc == 0 else "FAIL",
        }
        (stage_dir / "c_compile.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rc


def _make_append(name: str, values: list[str]) -> list[str]:
    return [f"{name} += {value}" for value in values]


def _cocotb_config_exe(python_exe: Path | None = None) -> str:
    candidate = (python_exe or Path(sys.executable)).with_name("cocotb-config")
    return str(candidate) if candidate.exists() else "cocotb-config"


def _cocotb_version(python_exe: Path) -> str | None:
    try:
        return subprocess.check_output(
            [str(python_exe), "-c", "import cocotb; print(cocotb.__version__)"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _cocotb_major(version: str) -> int | None:
    match = re.match(r"^(\d+)", version)
    return int(match.group(1)) if match else None


def _vcs_cocotb_python(root: Path) -> Path:
    """Select a cocotb<2 interpreter for VCS classic make."""
    candidates = [root / "venv" / "bin" / "python", Path(sys.executable)]
    seen: set[Path] = set()
    checked: list[str] = []
    for python_exe in candidates:
        if python_exe in seen or not python_exe.exists():
            continue
        seen.add(python_exe)
        version = _cocotb_version(python_exe)
        checked.append(f"{python_exe} ({version or 'no cocotb'})")
        if version is not None and (_cocotb_major(version) or 99) < 2:
            return python_exe
    raise ConfigError(
        "VCS classic cocotb make requires cocotb < 2.0. Checked: "
        + "; ".join(checked)
        + ". Install the repo requirements into the selected Python environment."
    )


def _first_cocotb_module(catalog: TestCatalog) -> str:
    for test in catalog.tests.values():
        return test.module
    return "dummy_test"


def _safe_build_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()) or "default"


def _cocotb_python_paths(root: Path, cocotb_data: dict[str, Any]) -> list[Path]:
    return [
        repo_path(root, str(cocotb_data.get("test_dir", ""))),
        repo_path(root, str(cocotb_data.get("python_root", ""))),
        *[
            repo_path(root, path)
            for path in as_str_list(cocotb_data.get("python_paths"), "cocotb.python_paths")
        ],
        # Simulator children get a rebuilt PYTHONPATH from this list (not the launcher's
        # ambient one), so the generated namespace bridge must be carried explicitly.
        root / "build" / "dv" / "python",
    ]


def _cocotb_build_info(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    tool: str,
) -> dict[str, Any]:
    build = build_cfg(flow, sim_cfg)
    target_name = _target_name(sim_cfg)
    run_target = selected_run_target(sim_cfg)
    compile_target = selected_compile_target(sim_cfg)
    options = build_options_cfg(build)
    filelist = repo_path(root, str(build.get("filelist", "")))
    top_module = str(build.get("top_module", ""))
    if not top_module:
        raise ConfigError(f"{flow.path}: [build].top_module is required")

    build_dir = required_path(run_target, "build_dir", "targets", str(flow.path))
    base_build = repo_path(root, build_dir) / tool
    if tool == "vcs":
        base_build /= _safe_build_component(target_name)
    if args.cov:
        base_build /= "coverage"
    build_args = _cocotb_build_args(tool, flow, root, build, run_target, compile_target, options, filelist, args)

    wave_format = _wave_format(args, tool)
    cov = coverage_cfg(sim_cfg)
    if args.cov:
        tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
        coverage_build_args = as_str_list(
            tool_cov.get("compile_args" if tool == "vcs" else "build_args"),
            f"coverage.{tool}.{'compile_args' if tool == 'vcs' else 'build_args'}",
        )
        build_args += render_tokens(
            coverage_build_args,
            {
                "tool": tool,
                "target": target_name,
                "build_dir": str(base_build),
                "build_cov_dir": str(base_build / "cov_build.vdb"),
                "cov_dir": str(base_build / "coverage"),
            },
        )

    if wave_format and tool == "verilator":
        if wave_format not in {"fst", "vcd"}:
            raise ConfigError(
                f"Verilator cocotb waves support `fst` or `vcd`, got `{args.waves}`"
            )
        trace_arg = "--trace-fst" if wave_format == "fst" else "--trace"
        if trace_arg not in build_args:
            build_args.append(trace_arg)

    if tool == "verilator":
        tool_ver = verilator_version(root)
    elif tool == "xcelium":
        tool_ver = xcelium_version(root)
    else:
        tool_ver = vcs_version(root)
    filelist_text = filelist.read_text(encoding="utf-8", errors="replace") if filelist.is_file() else str(filelist)
    public_scope_extra = (
        _verilator_public_scope_fingerprint(root, build) if tool == "verilator" else []
    )
    fingerprint = build_fingerprint(
        build_args=build_args,
        top_module=top_module,
        tool_version=tool_ver,
        filelist_text=filelist_text,
        extra=[
            *cache_key_extra(options),
            *_target_fingerprint_extra(target_name, run_target),
            *public_scope_extra,
            f"waves={wave_format}",
            f"cov={bool(args.cov)}",
        ],
    )
    sim_build = resolve_build_dir(base_build, options, fingerprint)
    return {
        "build": build,
        "target_name": target_name,
        "run_target": run_target,
        "compile_target": compile_target,
        "options": options,
        "filelist": filelist,
        "top_module": top_module,
        "base_build": base_build,
        "sim_build": sim_build,
        "fingerprint": fingerprint,
        "build_args": build_args,
        "wave_format": wave_format,
        "rebuild": bool(args.rebuild) or bool(options.get("rebuild", False)),
    }


def _cocotb_vcs_makefile(
    *,
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    args: argparse.Namespace,
    item: str | None,
    seed: int,
    item_dir: Path,
    makefile: Path,
    results_xml: Path,
    cov_dir: Path,
    waves_dir: Path,
    for_build: bool,
) -> dict[str, Any]:
    build = build_cfg(flow, sim_cfg)
    cocotb_data = cocotb_cfg(flow, sim_cfg)
    compile_target = selected_compile_target(sim_cfg)
    run_target = selected_run_target(sim_cfg)
    options = build_options_cfg(build)
    cov = coverage_cfg(sim_cfg)
    filelist = repo_path(root, str(build.get("filelist", "")))
    top_module = str(build.get("top_module", ""))
    if not top_module:
        raise ConfigError(f"{flow.path}: [build].top_module is required")
    build_info = _cocotb_build_info(flow, root, sim_cfg, args, "vcs")
    sim_build = build_info["sim_build"]
    module = catalog.tests[item].module if item else _first_cocotb_module(catalog)

    ctx = {
        "run_dir": str(item_dir),
        "results_dir": str(results_xml.parent),
        "results_xml": str(results_xml),
        "cov_dir": str(cov_dir),
        "build_dir": str(sim_build),
        "build_cov_dir": str(sim_build / "cov_build.vdb"),
        "seed": str(seed),
        "tool": "vcs",
        "item": item or "",
    }
    compile_args = [
        "-f",
        str(filelist),
        *[f"+define+{define}" for define in config_list(compile_target, "defines")],
        *[f"+define+{define}" for define in (args.define or [])],
        *(target_flags(run_target, "vcs") or target_flags(compile_target, "vcs")),
        *(args.comp_arg or []),
    ]
    sim_args = []
    if item is not None:
        test = catalog.tests[item]
        run_mode = selected_run_mode(sim_cfg, test, args)
        sim_args = [
            *sim_global_args(sim_cfg),
            *_render_run_test_args(run_mode, test, seed, root),
            *(args.sim_arg or []),
            *(args.plusarg or []),
        ]

    if args.cov:
        vcs_cov = cov.get("vcs", {}) if isinstance(cov.get("vcs", {}), dict) else {}
        compile_args += _render_list(
            as_str_list(vcs_cov.get("compile_args"), "coverage.vcs.compile_args"),
            ctx,
        )
        sim_args += _render_list(
            as_str_list(vcs_cov.get("sim_args"), "coverage.vcs.sim_args"),
            ctx,
        )
        if not args.dry_run and not for_build:
            cov_dir.mkdir(parents=True, exist_ok=True)
    wave_format = _wave_format(args, "vcs")
    if wave_format and item is not None:
        if not args.dry_run:
            waves_dir.mkdir(parents=True, exist_ok=True)
        range_info = _wave_range(args)
        if wave_format == "vpd":
            sim_args.append(f"+vpdfile={waves_dir / (item + '.vpd')}")
        elif wave_format == "fsdb":
            sim_args.append(f"+fsdbfile+{waves_dir / (item + '.fsdb')}")
            if range_info.get("start_ps") is not None:
                sim_args.append(f"+fsdb+dumpon+{format_time_ps(range_info['start_ps'])}")
            if range_info.get("end_ps") is not None:
                sim_args.append(f"+fsdb+dumpoff+{format_time_ps(range_info['end_ps'])}")

    python_paths = _cocotb_python_paths(root, cocotb_data)
    vcs_python = _vcs_cocotb_python(root)
    env = os.environ.copy()
    # cocotb's classic make flow runs the simulator as a separate process whose embedded
    # interpreter loads the venv's libpython (via cocotb-config) but does NOT auto-activate the
    # venv. The Python runner (verilator/xcelium) runs in-process so it inherits this venv's
    # site-packages for free; here we must add them and mark VIRTUAL_ENV so the embedded
    # interpreter finds cocotb. VCS classic make is pinned to cocotb 1.9.x because
    # cocotb 2.0's load_entry(argv) signature is incompatible with this VCS flow.
    venv_site = subprocess.check_output(
        [
            str(vcs_python),
            "-c",
            "import sysconfig; print('\\n'.join(p for p in {sysconfig.get_paths().get('purelib'), sysconfig.get_paths().get('platlib')} if p))",
        ],
        text=True,
    ).splitlines()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in [*python_paths, *venv_site] if str(path))
    env["VIRTUAL_ENV"] = str(vcs_python.parents[1])
    env["RANDOM_SEED"] = str(seed)
    env["PATH"] = os.pathsep.join([str(vcs_python.parent), env.get("PATH", "")])
    env = apply_option_env(options, env, None)

    make_lines = [
        "# Generated by tools/dv/run_dv.py. Do not edit.",
        "SIM := vcs",
        "TOPLEVEL_LANG := verilog",
        f"TOPLEVEL := {top_module}",
        f"MODULE := {module}",
        f"RANDOM_SEED := {seed}",
        f"COCOTB_RESULTS_FILE := {results_xml}",
        f"SIM_BUILD := {sim_build}",
        "",
        *_make_append("COMPILE_ARGS", compile_args),
        *_make_append("SIM_ARGS", sim_args),
        "",
        f"include $(shell {_cocotb_config_exe(vcs_python)} --makefiles)/Makefile.sim",
        "",
        ".PHONY: compile",
        "compile: $(SIM_BUILD)/simv",
        "",
    ]
    write_text_file(makefile, "\n".join(make_lines), args.dry_run)
    return {"env": env, "sim_build": sim_build}


def cocotb_build(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    args: argparse.Namespace,
    tool: str,
    stage_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
    """Build the reusable cocotb simulator model before per-test simulation."""
    if tool not in COCOTB_RUNNER_TOOLS | COCOTB_MAKE_TOOLS:
        raise ConfigError(f"cocotb build supports tool verilator|xcelium|vcs, got `{tool}`")

    console = console_from_args(args)
    target_name = _target_name(sim_cfg)
    if tool in COCOTB_MAKE_TOOLS:
        make_dir = stage_dir / "make"
        makefile = make_dir / f"Makefile.{tool}"
        results_xml = stage_dir / "results" / "results.xml"
        cov_dir = stage_dir / "coverage"
        waves_dir = stage_dir / "waves"
        data = _cocotb_vcs_makefile(
            flow=flow,
            root=root,
            sim_cfg=sim_cfg,
            catalog=catalog,
            args=args,
            item=None,
            seed=as_int(args.seed, "seed") or 1,
            item_dir=stage_dir,
            makefile=makefile,
            results_xml=results_xml,
            cov_dir=cov_dir,
            waves_dir=waves_dir,
            for_build=True,
        )
        console.artifact("build", data["sim_build"])
        console.artifact("makefile", makefile)
        rc = run_subprocess(
            ["make", "-f", str(makefile), "compile"],
            root,
            log_path,
            args.dry_run,
            script_path,
            env_path,
            args.quiet,
            cwd=make_dir,
            env=data["env"],
            verbose=args.verbose,
            timeout_sec=args.timeout,
        )
        if rc == 0:
            _mark_cocotb_prebuilt(args, target_name)
        return rc

    info = _cocotb_build_info(flow, root, sim_cfg, args, tool)
    build = info["build"]
    target_name = info["target_name"]
    options = info["options"]
    env = os.environ.copy()
    env = apply_option_env(
        options,
        env,
        build_verilator_cfg(build) if tool == "verilator" else None,
    )
    # Parallelize the cocotb-driven `make` C++ compile. The `build_jobs` option only
    # reaches Verilator's own codegen via `--build-jobs`; the cocotb runner invokes
    # `make -f Vtop.mk` separately. Until cocotb exposes a real per-build jobs API,
    # cocotb_make_jobs() maps the same config/CLI value onto that backend's make -j.
    _build_jobs = effective_build_jobs(options, _build_jobs_arg(args))
    if _build_jobs and _build_jobs > 1:
        env["MAKEFLAGS"] = f"-j{_build_jobs}"
        console.artifact("cocotb_make_jobs", str(_build_jobs))
    # Verilator-only: scope cocotb's global --public-flat-rw to the tb top (see
    # cocotb_public_scope). Empty/absent config -> cocotb's default behaviour is kept.
    public_scope_vlt = ""
    if tool == "verilator":
        _scope_rel = str(build_verilator_cfg(build).get("public_scope") or "").strip()
        if _scope_rel:
            public_scope_vlt = str(repo_path(root, _scope_rel))
            console.artifact("public_scope", public_scope_vlt)
    console.artifact("build", f"{info['sim_build']} (rebuild={info['rebuild']})")
    write_script(script_path, root, [sys.executable, "-c", "from cocotb.runner import get_runner"], args.dry_run)
    write_env_snapshot(env_path, env, args.dry_run)
    if args.dry_run:
        _mark_cocotb_prebuilt(args, target_name)
        return 0

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# cocotb {tool} pre-build\n")
        with backend_output(log, quiet=args.quiet, verbose=args.verbose):
            with progress_step(console, f"cocotb {tool} load runner", args.quiet):
                get_runner = get_cocotb_runner()
                runner = get_runner(tool)
            with progress_step(console, f"cocotb {tool} build model", args.quiet):
                with scoped_environ(env), cocotb_make_jobs(_build_jobs), cocotb_public_scope(public_scope_vlt):
                    runner.build(
                        sources=[],
                        hdl_toplevel=info["top_module"],
                        build_dir=info["sim_build"],
                        build_args=info["build_args"],
                        includes=[repo_path(root, value) for value in as_str_list(build.get("incdirs"), "build.incdirs")],
                        waves=bool(_wave_format(args, tool)),
                        always=info["rebuild"],
                    )
    _mark_cocotb_prebuilt(args, target_name)
    return 0


def _cocotb_make_sim(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str,
    args: argparse.Namespace,
    tool: str,
    item_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    seed: int,
) -> int:
    run_mode = selected_run_mode(sim_cfg, catalog.tests[item], args)
    cocotb_data = cocotb_cfg(flow, sim_cfg)

    results_dir = item_dir / "results"
    waves_dir = item_dir / "waves"
    cov_dir = item_dir / "coverage"
    make_dir = item_dir / "make"
    makefile = make_dir / f"Makefile.{tool}"
    results_xml = results_dir / "results.xml"
    data = _cocotb_vcs_makefile(
        flow=flow,
        root=root,
        sim_cfg=sim_cfg,
        catalog=catalog,
        args=args,
        item=item,
        seed=seed,
        item_dir=item_dir,
        makefile=makefile,
        results_xml=results_xml,
        cov_dir=cov_dir,
        waves_dir=waves_dir,
        for_build=False,
    )

    console = console_from_args(args)
    console.artifact("xml", results_xml)
    console.artifact("makefile", makefile)
    if args.cov:
        console.artifact("coverage", cov_dir)
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)
        _stage_firmware_outputs(root, sim_cfg, catalog.tests[item], make_dir)
        # The Python cocotb runner (verilator/xcelium) chdir's to test_dir, so tests load their
        # memory images by test_dir-relative $readmemh paths. cocotb's classic VCS make flow runs
        # in make_dir instead; stage the test_dir memory images into make_dir so the same relative
        # paths resolve identically under VCS (runtime-generated images under out/ are written by
        # the test into this same cwd).
        test_dir = repo_path(root, str(cocotb_data.get("test_dir", "")))
        if test_dir.is_dir():
            for pattern in ("*.hex", "*.parhex"):
                for src in sorted(test_dir.glob(pattern)):
                    shutil.copy2(src, make_dir / src.name)
        # cocotb's classic VCS make flow runs in make_dir, so stage the time-0 image there.
        _run_sim_prestage(
            root, cocotb_data, item, seed, make_dir,
            sim_args=_render_run_test_args(
                run_mode, catalog.tests[item], seed, root
            ),
        )
    # The make flow compiles and runs in one invocation, so the timeout bounds both.
    timeout_sec = resolve_timeout_sec(sim_cfg, catalog.tests[item], run_mode, args)
    return run_subprocess(
        ["make", "-f", str(makefile)],
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=make_dir,
        env=data["env"],
        verbose=args.verbose,
        timeout_sec=timeout_sec,
    )


def _run_sim_prestage(
    root: Path,
    cocotb_data: dict[str, Any],
    item: str,
    seed: int,
    cwd: Path,
    sim_args: list[str] | None = None,
) -> None:
    """Optional per-DUT pre-sim image hook.

    If the DUT's cocotb ``python_root`` contains ``dv_sim_prestage.py`` exposing
    ``stage(item, seed, cwd)``, invoke it after the memory-image staging and before
    the sim process launches. SEP uses this to write ``<cwd>/out/sep_efuse.hex`` for
    the ``sep_wrapper`` generic efuse model, which loads it in an RTL ``initial
    $readmemh`` at time 0 (before any cocotb Python runs). A DUT without the module
    (smc/dtp) is a no-op, so this never affects other flows.

    ``sim_args`` (the test's rendered plusargs) and ``root`` are passed as keyword
    args ONLY if the hook's ``stage`` accepts them, so a hook with the original
    ``stage(item, seed, cwd)`` signature still works. SEP uses ``sim_args`` to honor
    a ``+sep_efuse_preload`` override at t=0 the same way the test honors it at
    runtime.
    """
    py_root_rel = cocotb_data.get("python_root")
    if not py_root_rel:
        return
    py_root = repo_path(root, str(py_root_rel))
    hook_path = py_root / "dv_sim_prestage.py"
    if not hook_path.is_file():
        return
    import importlib.util
    import inspect

    if str(py_root) not in sys.path:
        sys.path.insert(0, str(py_root))
    spec = importlib.util.spec_from_file_location("dv_sim_prestage", hook_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    params = inspect.signature(module.stage).parameters
    kwargs: dict[str, Any] = {}
    if "sim_args" in params:
        kwargs["sim_args"] = sim_args or []
    if "root" in params:
        kwargs["root"] = str(root)
    module.stage(item, seed, cwd, **kwargs)


def cocotb_sim(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str,
    args: argparse.Namespace,
    tool: str,
    item_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    seed: int,
) -> int:
    if tool not in COCOTB_RUNNER_TOOLS | COCOTB_MAKE_TOOLS:
        raise ConfigError(
            f"cocotb sim supports tool verilator|xcelium|vcs, got `{tool}`"
        )
    if tool in COCOTB_MAKE_TOOLS:
        return _cocotb_make_sim(
            flow,
            root,
            sim_cfg,
            catalog,
            item,
            args,
            tool,
            item_dir,
            log_path,
            script_path,
            env_path,
            seed,
        )

    info = _cocotb_build_info(flow, root, sim_cfg, args, tool)
    build = info["build"]
    target_name = info["target_name"]
    cocotb_data = cocotb_cfg(flow, sim_cfg)
    options = info["options"]
    cov = coverage_cfg(sim_cfg)
    test = catalog.tests[item]
    run_mode = selected_run_mode(sim_cfg, test, args)

    results_dir = item_dir / "results"
    waves_dir = item_dir / "waves"
    cov_dir = item_dir / "coverage"
    results_xml = results_dir / "results.xml"
    build_args = list(info["build_args"])
    top_module = str(info["top_module"])
    sim_build = info["sim_build"]
    rebuild = bool(info["rebuild"])
    wave_format = str(info["wave_format"])
    test_args = [
        *sim_global_args(sim_cfg),
        *_render_run_test_args(run_mode, test, seed, root),
        *(args.sim_arg or []),
        *(args.plusarg or []),
    ]

    # Coverage: same cocotb test, simulator-native collection. Verilator does line/toggle only;
    # Xcelium collects full SV coverage. Both controlled by --cov and overridable via [coverage].
    if args.cov:
        tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
        coverage_ctx = {
            "cov_dir": str(cov_dir),
            "build_dir": str(sim_build),
            "tool": tool,
            "target": target_name,
            "item": item,
            "seed": str(seed),
        }
        test_args += render_tokens(
            [
                *as_str_list(tool_cov.get("sim_args"), f"coverage.{tool}.sim_args"),
                *as_str_list(tool_cov.get("test_args"), f"coverage.{tool}.test_args"),
            ],
            coverage_ctx,
        )
        if not args.dry_run:
            cov_dir.mkdir(parents=True, exist_ok=True)

    wave_format = _wave_format(args, tool)
    if wave_format:
        if not args.dry_run:
            waves_dir.mkdir(parents=True, exist_ok=True)
        if tool == "verilator":
            suffix = ".fst" if wave_format == "fst" else ".vcd"
            if wave_format == "fst":
                test_args.append("--trace-fst")
            test_args += ["--trace-file", str(waves_dir / (item + suffix))]
        elif tool == "xcelium":
            tcl_path = item_dir / "scripts" / f"waves.{item}.tcl"
            _xcelium_wave_tcl(
                tcl_path=tcl_path,
                waves_dir=waves_dir,
                item=item,
                wave_format=wave_format,
                range_info=_wave_range(args),
                dry_run=args.dry_run,
            )
            test_args += ["-input", str(tcl_path)]

    python_paths = _cocotb_python_paths(root, cocotb_data)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths if str(path))
    env["RANDOM_SEED"] = str(seed)
    env = apply_option_env(
        options,
        env,
        build_verilator_cfg(build) if tool == "verilator" else None,
    )
    public_scope_vlt = ""
    if tool == "verilator":
        _scope_rel = str(build_verilator_cfg(build).get("public_scope") or "").strip()
        if _scope_rel:
            public_scope_vlt = str(repo_path(root, _scope_rel))

    console = console_from_args(args)
    console.artifact("xml", results_xml)
    console.artifact("build", f"{sim_build} (rebuild={rebuild})")
    if args.cov:
        console.artifact("coverage", cov_dir)
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)
        _stage_firmware_outputs(root, sim_cfg, test, item_dir)
        # Temporary compatibility bridge: some legacy behavioral responders still
        # $readmemh/$fopen flat image names from the sim CWD at time 0, while cocotb
        # now runs each test from its per-test run dir. Stage source test-dir
        # images until those responders/tests use explicit configured image paths.
        # Per-test boot_firmware staging still overwrites the TCM images it owns.
        src_test_dir = repo_path(root, str(cocotb_data.get("test_dir", "")))
        if src_test_dir.is_dir():
            for pattern in ("*.hex", "*.parhex"):
                for asset in src_test_dir.glob(pattern):
                    shutil.copy2(asset, item_dir / asset.name)
        # cocotb runner chdir's to item_dir, so a time-0 image hook writes there.
        _run_sim_prestage(
            root, cocotb_data, item, seed, item_dir,
            sim_args=_render_run_test_args(
                selected_run_mode(sim_cfg, catalog.tests[item], args),
                test,
                seed,
                root,
            ),
        )

    runner_py = script_path.with_suffix(".py")
    payload = {
        "tool": tool,
        "top_module": top_module,
        "test_module": test.module,
        "test_dir": str(item_dir),
        "sim_build": str(sim_build),
        "build_args": [str(arg) for arg in build_args],
        "includes": [
            str(repo_path(root, value))
            for value in as_str_list(build.get("incdirs"), "build.incdirs")
        ],
        "test_args": [str(arg) for arg in test_args],
        "results_xml": str(results_xml),
        "waves": bool(wave_format),
        "wave_format": wave_format,
        "seed": int(seed),
        "do_build": not _is_cocotb_prebuilt(args, target_name),
        "rebuild": bool(rebuild),
        "python_paths": [str(path) for path in python_paths if str(path)],
        "public_scope_vlt": public_scope_vlt,
    }
    runner_body = f"""#!/usr/bin/env python3
import os
import sys
from contextlib import contextmanager

payload = {payload!r}

for path in payload["python_paths"]:
    if path and path not in sys.path:
        sys.path.insert(0, path)

try:
    from cocotb.runner import get_runner
except ImportError:
    from cocotb_tools.runner import get_runner

@contextmanager
def scoped_public_scope(vlt_path):
    if not vlt_path:
        yield
        return
    import importlib
    from pathlib import Path
    if not Path(vlt_path).is_file():
        raise RuntimeError(f"configured Verilator public_scope file does not exist: {{vlt_path}}")
    patched = []
    for module_name in ("cocotb.runner", "cocotb_tools.runner"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        cls = getattr(module, "Verilator", None)
        original = getattr(cls, "_build_command", None)
        if cls is None or original is None:
            continue
        def make_wrapper(orig, vlt):
            def _build_command(self):
                scoped = []
                for cmd in orig(self):
                    if not isinstance(cmd, (list, tuple)):
                        scoped.append(cmd)
                        continue
                    toks = [tok for tok in cmd if tok != "--public-flat-rw"]
                    if "--vpi" in toks and vlt not in toks:
                        toks.insert(toks.index("--vpi") + 1, vlt)
                    scoped.append(toks)
                return scoped
            return _build_command
        cls._build_command = make_wrapper(original, vlt_path)
        patched.append((cls, original))
    if not patched:
        raise RuntimeError("configured Verilator public_scope but no cocotb Verilator runner was patched")
    try:
        yield
    finally:
        for cls, original in patched:
            cls._build_command = original

@contextmanager
def scoped_verilator_wave_format(tool, wave_format):
    if tool != "verilator" or wave_format != "fst":
        yield
        return
    import importlib
    patched = []
    for module_name in ("cocotb.runner", "cocotb_tools.runner"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        cls = getattr(module, "Verilator", None)
        original_build = getattr(cls, "_build_command", None)
        original_test = getattr(cls, "_test_command", None)
        if cls is None or original_build is None or original_test is None:
            continue
        def make_build_wrapper(orig):
            def _build_command(self):
                formatted = []
                for cmd in orig(self):
                    if not isinstance(cmd, (list, tuple)):
                        formatted.append(cmd)
                        continue
                    toks = list(cmd)
                    if "Vtop.mk" in toks and "VM_TRACE_FST=1" not in toks:
                        toks.append("VM_TRACE_FST=1")
                    if "--trace" in toks and "--trace-fst" not in toks:
                        toks.insert(toks.index("--trace") + 1, "--trace-fst")
                    formatted.append(toks)
                return formatted
            return _build_command
        def make_test_wrapper(orig):
            def _test_command(self):
                formatted = []
                for cmd in orig(self):
                    if not isinstance(cmd, (list, tuple)):
                        formatted.append(cmd)
                        continue
                    toks = list(cmd)
                    if "--trace" in toks and "--trace-fst" not in toks:
                        toks.insert(toks.index("--trace") + 1, "--trace-fst")
                    formatted.append(toks)
                return formatted
            return _test_command
        cls._build_command = make_build_wrapper(original_build)
        cls._test_command = make_test_wrapper(original_test)
        patched.append((cls, original_build, original_test))
    if not patched:
        raise RuntimeError("Verilator FST requested but no cocotb Verilator runner was patched")
    try:
        yield
    finally:
        for cls, original_build, original_test in patched:
            cls._build_command = original_build
            cls._test_command = original_test

print(f"# cocotb {{payload['tool']}} runner", flush=True)
runner = get_runner(payload["tool"])
with scoped_public_scope(payload["public_scope_vlt"]), scoped_verilator_wave_format(payload["tool"], payload["wave_format"]):
    if payload["do_build"]:
        print(f"# cocotb {{payload['tool']}} build model", flush=True)
        runner.build(
            sources=[],
            hdl_toplevel=payload["top_module"],
            build_dir=payload["sim_build"],
            build_args=payload["build_args"],
            includes=payload["includes"],
            waves=payload["waves"],
            always=payload["rebuild"],
        )
    else:
        print(f"# cocotb {{payload['tool']}} build skipped: pre-built during elaborate", flush=True)

    runner.test(
        hdl_toplevel=payload["top_module"],
        hdl_toplevel_lang="verilog",
        test_module=payload["test_module"],
        build_dir=payload["sim_build"],
        test_dir=payload["test_dir"],
        test_args=payload["test_args"],
        results_xml=payload["results_xml"],
        waves=payload["waves"],
        seed=payload["seed"],
        extra_env=dict(os.environ),
    )
"""
    write_text_file(runner_py, runner_body, args.dry_run)
    timeout_sec = resolve_timeout_sec(sim_cfg, test, run_mode, args)
    return run_subprocess(
        [sys.executable, str(runner_py)],
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        env=env,
        verbose=args.verbose,
        timeout_sec=timeout_sec,
    )


# --- VCS (Synopsys) stages ----------------------------------------------------------------------
# Three-step UUM/UVM flow: vlogan (analyze) -> vcs (elaborate -> simv) -> simv (run). Two-step folds
# analyze+elaborate into one `vcs -f <filelist>` build. The simv is the reusable build artifact, so
# every seed in a regression runs the same simv (compile once, sim many) — the commercial analogue
# of the cocotb `always=false` decouple.


def _vcs_defines(compile_target: dict[str, Any], args: argparse.Namespace) -> list[str]:
    defines = [f"+define+{d}" for d in config_list(compile_target, "defines")]
    defines += [f"+define+{d}" for d in (args.define or [])]
    return defines


def _vcs_preamble(vcs_cfg: dict[str, Any], framework: str) -> list[str]:
    pre: list[str] = []
    if bool(vcs_cfg.get("sverilog", True)):
        pre.append("-sverilog")
    pre.append("-full64")
    if bool(vcs_cfg.get("uvm", framework == "uvm")):
        pre += ["-ntb_opts", "uvm"]
    timescale = str(vcs_cfg.get("timescale", "")).strip()
    if timescale:
        pre.append(f"-timescale={timescale}")
    return pre


def _vcs_resolve_build(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Resolve the (fingerprinted) VCS build dir and simv path. Shared by build and sim stages so
    the sim stage locates the exact simv the build stage produced."""
    build = build_cfg(flow, sim_cfg)
    target_name = _target_name(sim_cfg)
    compile_target = selected_compile_target(sim_cfg)
    options = build_options_cfg(build)
    vcs_cfg = build_vcs_cfg(build)
    top = str(build.get("top_module", ""))
    if not top:
        raise ConfigError(f"{flow.path}: [build].top_module is required")
    filelist = repo_path(root, str(build.get("filelist", "")))
    base_build = repo_path(root, required_path(build, "work_dir", "build", str(flow.path)))

    elab_args = [
        *_vcs_preamble(vcs_cfg, flow.framework),
        *_vcs_defines(compile_target, args),
        *target_flags(compile_target, "vcs"),
        *vcs_build_args(options, vcs_cfg, _build_jobs_arg(args)),
    ]
    wave_format = _wave_format(args, "vcs")
    if wave_format:
        elab_args.append("-debug_access+all")

    filelist_text = filelist.read_text(encoding="utf-8", errors="replace") if filelist.is_file() else str(filelist)
    fingerprint = build_fingerprint(
        build_args=elab_args,
        top_module=top,
        tool_version=vcs_version(root),
        filelist_text=filelist_text,
        extra=[
            *cache_key_extra(options),
            *_target_fingerprint_extra(target_name, compile_target),
            f"waves={wave_format}",
        ],
    )
    build_dir = resolve_build_dir(base_build, options, fingerprint)
    return {
        "build": build,
        "target_name": target_name,
        "compile_target": compile_target,
        "vcs_cfg": vcs_cfg,
        "top": top,
        "filelist": filelist,
        "build_dir": build_dir,
        "fingerprint": fingerprint,
        "simv": build_dir / "simv",
        "elab_args": elab_args,
    }


def vcs_analyze(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace, log_path: Path, script_path: Path, env_path: Path) -> int:
    """Three-step `compile` stage: analyze sources into the work library with vlogan."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    vcs_cfg = info["vcs_cfg"]
    analyze_argv = [
        "vlogan",
        *_vcs_preamble(vcs_cfg, flow.framework),
        *_vcs_defines(info["compile_target"], args),
        *target_flags(info["compile_target"], "vcs"),
        *as_str_list(vcs_cfg.get("compile_args"), "build.vcs.compile_args"),
        *as_str_list(vcs_cfg.get("analyze_args"), "build.vcs.analyze_args"),
        *(args.comp_arg or []),
        "-f",
        str(info["filelist"]),
    ]
    if bool(vcs_cfg.get("uvm", flow.framework == "uvm")):
        # In a split vlogan -> vcs flow, -ntb_opts uvm on the user-source
        # invocation exposes the UVM macros but does not analyze uvm_pkg first.
        # Precompile the simulator-owned package in the same work library before
        # importing it from the OCAH and DUT UVM packages.
        argv = [
            "bash",
            "-c",
            "set -euo pipefail\nvlogan -full64 -ntb_opts uvm\nexec \"$@\"",
            "vcs-analyze",
            *analyze_argv,
        ]
    else:
        argv = analyze_argv
    console_from_args(args).artifact("build", info["build_dir"])
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=info["build_dir"], verbose=args.verbose, timeout_sec=args.timeout)


def vcs_build(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace, log_path: Path, script_path: Path, env_path: Path, *, include_filelist: bool) -> int:
    """Elaborate to a `simv`. `include_filelist=True` is the two-step combined build (vcs -f ...);
    `False` is the three-step elaborate that consumes the already-analyzed library."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    build_dir = info["build_dir"]
    vcs_cfg = info["vcs_cfg"]
    argv = ["vcs", *info["elab_args"]]
    if include_filelist:
        argv += ["-f", str(info["filelist"])]
    argv += [
        info["top"],
        "-o",
        str(info["simv"]),
        f"-Mdir={build_dir / 'csrc'}",
        *as_str_list(vcs_cfg.get("elab_args"), "build.vcs.elab_args"),
        *(args.comp_arg or []),
    ]
    console = console_from_args(args)
    console.artifact("build", build_dir)
    console.artifact("simv", info["simv"])
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=build_dir, verbose=args.verbose, timeout_sec=args.timeout)


def vcs_sim(flow: Flow, root: Path, sim_cfg: dict[str, Any], catalog: TestCatalog, item: str, args: argparse.Namespace, item_dir: Path, log_path: Path, script_path: Path, env_path: Path, seed: int) -> int:
    """Run a built simv for one test/seed. The simv is reused across all seeds."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    simv = info["simv"]
    vcs_cfg = info["vcs_cfg"]
    test = catalog.tests[item]
    run_mode = selected_run_mode(sim_cfg, test, args)
    results_dir = item_dir / "results"
    waves_dir = item_dir / "waves"
    uvm_test = test.module or test.name

    argv = [str(simv)]
    if bool(vcs_cfg.get("uvm", flow.framework == "uvm")):
        argv.append(f"+UVM_TESTNAME={uvm_test}")
    argv.append(f"+ntb_random_seed={seed}")
    argv += [
        *sim_global_args(sim_cfg),
        *_render_run_test_args(run_mode, test, seed, root),
        *(args.sim_arg or []),
        *(args.plusarg or []),
    ]
    wave_format = _wave_format(args, "vcs")
    if wave_format:
        if not args.dry_run:
            waves_dir.mkdir(parents=True, exist_ok=True)
        range_info = _wave_range(args)
        if wave_format == "vpd":
            argv.append(f"+vpdfile={waves_dir / (item + '.vpd')}")
        elif wave_format == "fsdb":
            argv.append(f"+fsdbfile+{waves_dir / (item + '.fsdb')}")
            if range_info.get("start_ps") is not None:
                argv.append(f"+fsdb+dumpon+{format_time_ps(range_info['start_ps'])}")
            if range_info.get("end_ps") is not None:
                argv.append(f"+fsdb+dumpoff+{format_time_ps(range_info['end_ps'])}")
    console = console_from_args(args)
    console.artifact("simv", simv)
    console.artifact("test", f"{uvm_test} seed={seed}")
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)
    timeout_sec = resolve_timeout_sec(sim_cfg, test, run_mode, args)
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=item_dir, verbose=args.verbose, timeout_sec=timeout_sec)


# --- Xcelium (Cadence) stages -------------------------------------------------------------------
# Three-step flow: xmvlog (analyze) -> xmelab (elaborate -> snapshot) -> xmsim (simulate). The
# elaborated snapshot is the reusable build artifact (the analogue of VCS simv): every seed in a
# regression runs the same snapshot via `xmsim -svseed <seed>`. The combined two-step build is
# `xrun -elaborate` (analyze+elaborate -> snapshot, no run).


def _xcelium_defines(compile_target: dict[str, Any], args: argparse.Namespace) -> list[str]:
    defines = [f"+define+{d}" for d in config_list(compile_target, "defines")]
    defines += [f"+define+{d}" for d in (args.define or [])]
    return defines


def _xcelium_common(xcelium_cfg: dict[str, Any], framework: str) -> list[str]:
    common: list[str] = []
    if bool(xcelium_cfg.get("uvm", framework == "uvm")):
        common.append("-uvm")
    timescale = str(xcelium_cfg.get("timescale", "")).strip()
    if timescale:
        common += ["-timescale", timescale]
    return common


def _xcelium_resolve_build(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Resolve the (fingerprinted) Xcelium build dir + snapshot name. Shared by build and sim stages
    so the sim stage locates the exact snapshot the build stage produced."""
    build = build_cfg(flow, sim_cfg)
    target_name = _target_name(sim_cfg)
    compile_target = selected_compile_target(sim_cfg)
    options = build_options_cfg(build)
    xcelium_cfg = build_xcelium_cfg(build)
    top = str(build.get("top_module", ""))
    if not top:
        raise ConfigError(f"{flow.path}: [build].top_module is required")
    filelist = repo_path(root, str(build.get("filelist", "")))
    base_build = repo_path(root, required_path(build, "work_dir", "build", str(flow.path)))
    snapshot = str(xcelium_cfg.get("snapshot", top))

    elab_args = [
        *_xcelium_common(xcelium_cfg, flow.framework),
        *target_flags(compile_target, "xcelium"),
        *as_str_list(xcelium_cfg.get("elab_args"), "build.xcelium.elab_args"),
        *xcelium_build_args(options, xcelium_cfg, _build_jobs_arg(args)),
    ]
    wave_format = _wave_format(args, "xcelium")
    if wave_format:
        elab_args += ["-access", "+rwc"]

    filelist_text = filelist.read_text(encoding="utf-8", errors="replace") if filelist.is_file() else str(filelist)
    fingerprint = build_fingerprint(
        build_args=[*elab_args, *_xcelium_defines(compile_target, args)],
        top_module=top,
        tool_version=xcelium_version(root),
        filelist_text=filelist_text,
        extra=[
            *cache_key_extra(options),
            *_target_fingerprint_extra(target_name, compile_target),
            f"waves={wave_format}",
        ],
    )
    build_dir = resolve_build_dir(base_build, options, fingerprint)
    return {
        "target_name": target_name,
        "compile_target": compile_target,
        "xcelium_cfg": xcelium_cfg,
        "top": top,
        "filelist": filelist,
        "build_dir": build_dir,
        "fingerprint": fingerprint,
        "snapshot": snapshot,
        "elab_args": elab_args,
    }


def xcelium_analyze(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace, log_path: Path, script_path: Path, env_path: Path) -> int:
    """Three-step `compile` stage: analyze sources into the work library with xmvlog."""
    info = _xcelium_resolve_build(flow, root, sim_cfg, args)
    xcelium_cfg = info["xcelium_cfg"]
    argv = [
        "xmvlog",
        "-sv",
        *_xcelium_common(xcelium_cfg, flow.framework),
        *_xcelium_defines(info["compile_target"], args),
        *target_flags(info["compile_target"], "xcelium"),
        *as_str_list(xcelium_cfg.get("compile_args"), "build.xcelium.compile_args"),
        *as_str_list(xcelium_cfg.get("analyze_args"), "build.xcelium.analyze_args"),
        *(args.comp_arg or []),
        "-f",
        str(info["filelist"]),
    ]
    console_from_args(args).artifact("build", info["build_dir"])
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=info["build_dir"], verbose=args.verbose, timeout_sec=args.timeout)


def xcelium_build(flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace, log_path: Path, script_path: Path, env_path: Path, *, include_filelist: bool) -> int:
    """Elaborate to a snapshot. `include_filelist=True` is the two-step combined build
    (`xrun -elaborate -f <filelist>`); `False` is the three-step `xmelab` after analysis."""
    info = _xcelium_resolve_build(flow, root, sim_cfg, args)
    build_dir = info["build_dir"]
    if include_filelist:
        argv = [
            "xrun",
            "-elaborate",
            "-sv",
            *info["elab_args"],
            *_xcelium_defines(info["compile_target"], args),
            "-snapshot",
            info["snapshot"],
            *(args.comp_arg or []),
            "-f",
            str(info["filelist"]),
            info["top"],
        ]
    else:
        argv = [
            "xmelab",
            *info["elab_args"],
            "-snapshot",
            info["snapshot"],
            *(args.comp_arg or []),
            info["top"],
        ]
    console = console_from_args(args)
    console.artifact("build", build_dir)
    console.artifact("snapshot", info["snapshot"])
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=build_dir, verbose=args.verbose, timeout_sec=args.timeout)


def xcelium_sim(flow: Flow, root: Path, sim_cfg: dict[str, Any], catalog: TestCatalog, item: str, args: argparse.Namespace, item_dir: Path, log_path: Path, script_path: Path, env_path: Path, seed: int) -> int:
    """Run a built snapshot for one test/seed with xmsim. The snapshot is reused across all seeds."""
    info = _xcelium_resolve_build(flow, root, sim_cfg, args)
    xcelium_cfg = info["xcelium_cfg"]
    test = catalog.tests[item]
    run_mode = selected_run_mode(sim_cfg, test, args)
    results_dir = item_dir / "results"
    waves_dir = item_dir / "waves"
    uvm_test = test.module or test.name

    argv = ["xmsim", "-svseed", str(seed), "-xmlibdirpath", str(info["build_dir"])]
    if bool(xcelium_cfg.get("uvm", flow.framework == "uvm")):
        argv.append(f"+UVM_TESTNAME={uvm_test}")
    argv += [
        *sim_global_args(sim_cfg),
        *_render_run_test_args(run_mode, test, seed, root),
        *(args.sim_arg or []),
        *(args.plusarg or []),
    ]
    wave_format = _wave_format(args, "xcelium")
    if wave_format:
        if not args.dry_run:
            waves_dir.mkdir(parents=True, exist_ok=True)
        if wave_format == "shm":
            tcl_path = item_dir / "scripts" / f"waves.{item}.tcl"
            _xcelium_wave_tcl(
                tcl_path=tcl_path,
                waves_dir=waves_dir,
                item=item,
                wave_format=wave_format,
                range_info=_wave_range(args),
                dry_run=args.dry_run,
            )
            argv += ["-input", str(tcl_path)]
    argv.append(info["snapshot"])
    console = console_from_args(args)
    console.artifact("snapshot", info["snapshot"])
    console.artifact("test", f"{uvm_test} seed={seed}")
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)
    timeout_sec = resolve_timeout_sec(sim_cfg, test, run_mode, args)
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=item_dir, verbose=args.verbose, timeout_sec=timeout_sec)


# --- Coverage merge/report ----------------------------------------------------------------------
# Simulation owns native database collection. These stages select the final leaf artifacts, merge
# only compatible databases, and normalize vendor reports under `<run_dir>/cov/`.


def _float_cfg(value: Any, key: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"`{key}` must be a number") from exc


def _coverage_tool_version(tool: str, root: Path) -> str:
    if tool == "verilator":
        return verilator_version(root)
    if tool == "vcs":
        return vcs_version(root)
    if tool == "xcelium":
        return xcelium_version(root)
    return "unknown"


def _coverage_supported_metrics(args: argparse.Namespace, tool: str) -> list[str]:
    simulators = getattr(args, "_simulators", {})
    tool_cfg = simulators.get(tool, {}) if isinstance(simulators, dict) else {}
    declared = (
        as_str_list(tool_cfg.get("supports_cov"), f"simulators.{tool}.supports_cov")
        if isinstance(tool_cfg, dict)
        else []
    )
    return [metric for metric in declared if metric in CANONICAL_METRICS]


def _coverage_design_db(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    tool_cov: dict[str, Any],
    args: argparse.Namespace,
) -> Path | None:
    explicit = tool_cov.get("design_db")
    if isinstance(explicit, str) and explicit:
        return _repo_or_dut_path(root, flow, explicit)
    template = tool_cov.get("design_artifact")
    if not isinstance(template, str) or not template:
        return None
    build_info = _cocotb_build_info(flow, root, sim_cfg, args, "vcs")
    build_dir = Path(build_info["sim_build"])
    target_name = _safe_build_component(_target_name(sim_cfg))
    rendered = render_tokens(
        [template],
        {
            "build_dir": str(build_dir),
            "build_cov_dir": str(build_dir / "cov_build.vdb"),
            "tool": "vcs",
            "target": target_name,
        },
    )[0]
    return Path(rendered)


def _coverage_auxiliary_files(
    flow: Flow,
    root: Path,
    tool_cov: dict[str, Any],
    key: str,
) -> list[str]:
    paths = [
        str(_repo_or_dut_path(root, flow, value))
        for value in as_str_list(tool_cov.get(key), f"coverage.{key}")
    ]
    missing = [path for path in paths if not Path(path).is_file()]
    if missing:
        raise ConfigError(
            f"coverage.{key} references missing file(s): {', '.join(missing)}"
        )
    return paths


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage_policy(
    flow: Flow,
    root: Path,
    tool: str,
    tool_cov: dict[str, Any],
) -> CoveragePolicy | None:
    configured = tool_cov.get("policy_file")
    if configured is not None:
        if not isinstance(configured, str) or not configured:
            raise ConfigError(f"coverage.{tool}.policy_file must be a non-empty string")
        path = _repo_or_dut_path(root, flow, configured)
        if not path.is_file():
            raise ConfigError(f"coverage policy does not exist: {path}")
        return load_coverage_policy(path, expected_dut=flow.name)
    canonical = flow.path.parent / "cov" / "config" / tool / "coverage_policy.toml"
    if canonical.is_file():
        return load_coverage_policy(canonical, expected_dut=flow.name)
    return None


def _legacy_coverage_policy_args(
    *,
    tool: str,
    phase: str,
    exclusions: list[str],
    waivers: list[str],
) -> list[str]:
    if not exclusions and not waivers:
        return []
    if tool == "vcs" and phase == "report" and not waivers:
        argv: list[str] = []
        for path in exclusions:
            argv.extend(["-elfile", path])
        return argv
    raise ConfigError(
        f"{tool} coverage auxiliary files require coverage_policy.toml native_files "
        "with explicit backend arguments"
    )


def _closure_scalar_metrics(details: Any) -> dict[str, float]:
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


def coverage_stage(flow: Flow, root: Path, sim_cfg: dict[str, Any], tool: str, run_dir: Path, phase: str, args: argparse.Namespace, log_path: Path, script_path: Path, env_path: Path, quiet: bool) -> int:
    cov = coverage_cfg(sim_cfg)
    tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
    if not tool_cov:
        raise ConfigError(f"no coverage configuration is available for tool `{tool}`")

    cov_dir = run_dir / "cov"
    merged_name = tool_cov.get("merged_name")
    if not isinstance(merged_name, str) or not merged_name:
        raise ConfigError(f"coverage.{tool}.merged_name must be a non-empty string")
    merged = cov_dir / merged_name
    report_dir = cov_dir / "report"
    manifest_path = cov_dir / "coverage.json"
    summary_path = report_dir / "summary.json"
    raw_details_path = report_dir / "coverage-details.raw.json"
    details_path = report_dir / "coverage-details.json"
    application_path = report_dir / "policy-application.json"
    parser = str(tool_cov.get("parser", ""))
    backend = str(tool_cov.get("backend") or parser or tool)
    supported_metrics = _coverage_supported_metrics(args, tool)
    exclusions = _coverage_auxiliary_files(flow, root, tool_cov, "exclude_files")
    waivers = _coverage_auxiliary_files(flow, root, tool_cov, "waiver_files")
    policy = _coverage_policy(flow, root, tool, tool_cov)
    design_db = _coverage_design_db(flow, root, sim_cfg, tool_cov, args)
    ctx = {
        "run_dir": str(run_dir),
        "cov_dir": str(cov_dir),
        "merged": str(merged),
        "report": str(report_dir),
        "tool": tool,
        "design_db": str(design_db or ""),
    }

    key = "merge_cmd" if phase == "merge" else "report_cmd"
    template = as_str_list(tool_cov.get(key), f"coverage.{tool}.{key}")
    if not template:
        raise ConfigError(f"coverage.{tool}.{key} must not be empty")

    if args.dry_run:
        dry_inputs = [str(run_dir / "<coverage-input>")] if phase == "merge" else []
        policy_args = [
            *native_policy_args(policy, tool=tool, phase=phase),
            *_legacy_coverage_policy_args(
                tool=tool,
                phase=phase,
                exclusions=exclusions,
                waivers=waivers,
            ),
        ]
        return run_subprocess(
            [*render_tokens(template, ctx, dry_inputs), *policy_args],
            root,
            log_path,
            True,
            script_path,
            env_path,
            quiet,
            cwd=cov_dir,
            verbose=args.verbose,
            timeout_sec=args.timeout,
        )

    cov_dir.mkdir(parents=True, exist_ok=True)
    if phase == "merge":
        glob_pattern = str(tool_cov.get("input_glob", ""))
        discovery = discover_coverage_inputs(
            root=root,
            run_dir=run_dir,
            flow=flow.name,
            tool=tool,
            fallback_glob=glob_pattern,
        )
        if not discovery.inputs:
            raise CoverageError(
                f"coverage was requested but no usable inputs were found under "
                f"{repo_rel(root, run_dir)}"
            )
        if "{design_db}" in " ".join(template):
            if design_db is None or not artifact_ready(design_db):
                raise CoverageError(
                    f"required design coverage database is missing or empty: {design_db}"
                )
        manifest = new_manifest(
            flow=flow.name,
            tool=tool,
            parser=parser,
            supported_metrics=supported_metrics,
            discovery=discovery,
            merged=merged,
            root=root,
            exclude_files=[repo_rel(root, value) or value for value in exclusions],
            waiver_files=[repo_rel(root, value) or value for value in waivers],
        )
        manifest["backend"] = backend
        manifest["tool_version"] = _coverage_tool_version(tool, root)
        manifest["policy"] = {
            "path": repo_rel(root, policy.path) if policy else None,
            "sha256": policy.sha256 if policy else None,
            "scope_epoch": policy.scope_epoch if policy else None,
            "native_files": [
                {
                    **entry,
                    "path": repo_rel(root, entry["path"]),
                }
                for entry in native_policy_manifest(policy)
            ],
            "legacy_exclusions": [
                {"path": repo_rel(root, path), "sha256": _file_sha256(path)}
                for path in exclusions
            ],
            "legacy_waivers": [
                {"path": repo_rel(root, path), "sha256": _file_sha256(path)}
                for path in waivers
            ],
        }
        if design_db is not None:
            manifest["artifacts"]["design_db"] = repo_rel(root, design_db)
        write_json(manifest_path, manifest)
        input_paths = [
            str(repo_path(root, entry.path))
            for entry in discovery.inputs
        ]
        argv = [
            *render_tokens(template, ctx, input_paths),
            *native_policy_args(policy, tool=tool, phase="merge"),
            *_legacy_coverage_policy_args(
                tool=tool,
                phase="merge",
                exclusions=exclusions,
                waivers=waivers,
            ),
        ]
        rc = run_subprocess(
            argv,
            root,
            log_path,
            False,
            script_path,
            env_path,
            quiet,
            cwd=cov_dir,
            verbose=args.verbose,
            timeout_sec=args.timeout,
        )
        manifest["status"] = "ERROR" if rc else "PASS"
        manifest["merge_return_code"] = rc
        write_json(manifest_path, manifest)
        if rc != 0:
            return rc
        if not artifact_ready(merged):
            manifest["status"] = "ERROR"
            manifest["error"] = "merge command completed without a usable merged database"
            write_json(manifest_path, manifest)
            raise CoverageError(manifest["error"])
        return 0

    manifest = load_manifest(manifest_path)
    if manifest.get("dut") != flow.name or manifest.get("tool") != tool:
        raise CoverageError(
            "coverage manifest DUT/tool does not match the requested report stage"
        )
    merged_value = (manifest.get("artifacts") or {}).get("merged")
    if not isinstance(merged_value, str):
        raise CoverageError("coverage manifest does not record a merged database")
    merged = repo_path(root, merged_value)
    ctx["merged"] = str(merged)
    if not artifact_ready(merged):
        raise CoverageError(f"merged coverage database is missing or empty: {merged}")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_policy_args = [
        *native_policy_args(policy, tool=tool, phase="report"),
        *_legacy_coverage_policy_args(
            tool=tool,
            phase="report",
            exclusions=exclusions,
            waivers=waivers,
        ),
    ]
    rc = run_subprocess(
        [*render_tokens(template, ctx), *report_policy_args],
        root,
        log_path,
        False,
        script_path,
        env_path,
        quiet,
        cwd=cov_dir,
        verbose=args.verbose,
        timeout_sec=args.timeout,
    )
    if rc != 0:
        manifest["status"] = "ERROR"
        manifest["report_return_code"] = rc
        write_json(manifest_path, manifest)
        return rc

    threshold = args.fail_under
    if threshold is None:
        threshold = _float_cfg(tool_cov.get("fail_under"), f"coverage.{tool}.fail_under")
    threshold = threshold if threshold is not None else 0.0
    scalar_metrics, total_percent = parse_coverage_report(
        parser=parser,
        report_dir=report_dir,
        merged=merged,
        log_path=log_path,
    )
    details = parse_coverage_details(
        parser=parser,
        dut=flow.name,
        tool=tool,
        target=manifest.get("target"),
        build_fingerprint=manifest.get("build_fingerprint"),
        report_dir=report_dir,
        merged=merged,
        log_path=log_path,
    )
    write_json(raw_details_path, details.to_dict())
    details = apply_coverage_policy(details, policy)
    if details.policy_application.get("policy"):
        details.policy_application["policy"] = repo_rel(
            root, details.policy_application["policy"]
        )
    for entry in details.policy_application.get("native_files", []):
        if isinstance(entry, dict) and entry.get("path"):
            entry["path"] = repo_rel(root, entry["path"])
    effective_details = details.to_dict()
    write_json(details_path, effective_details)
    write_json(application_path, details.policy_application)
    metrics = dict(scalar_metrics)
    metrics.update(_closure_scalar_metrics(details))
    compatibility_threshold_met = total_percent >= threshold
    policy_threshold_met = all(
        bool(outcome.get("met")) for outcome in details.thresholds
    )
    threshold_met = compatibility_threshold_met and policy_threshold_met
    status = "PASS" if threshold_met else "FAIL"
    holes_summary = effective_details.get("holes_summary", {})
    summary_payload = {
        "schema_version": 2,
        "dut": flow.name,
        "tool": tool,
        "backend": backend,
        "tool_versions": {tool: _coverage_tool_version(tool, root)},
        "supported_metrics": supported_metrics,
        "metrics": metrics,
        "overall_percent": total_percent,
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
            entry.get("path")
            for entry in manifest.get("inputs", [])
            if isinstance(entry, dict)
        ],
        "artifacts": {
            "merged": repo_rel(root, merged),
            "report": repo_rel(root, report_dir),
            "json": repo_rel(root, summary_path),
            "manifest": repo_rel(root, manifest_path),
            "coverage_details_raw": repo_rel(root, raw_details_path),
            "coverage_details": repo_rel(root, details_path),
            "policy_application": repo_rel(root, application_path),
        },
    }
    write_json(summary_path, summary_payload)
    manifest["status"] = status
    manifest["metrics"] = metrics
    manifest["overall_percent"] = total_percent
    manifest["threshold"] = threshold
    manifest["threshold_met"] = threshold_met
    manifest["policy_thresholds"] = details.thresholds
    manifest["comparison_key"] = details.comparison_key
    manifest["scope_fingerprint"] = details.scope_fingerprint
    manifest["policy_fingerprint"] = details.policy_fingerprint
    manifest["holes_summary"] = holes_summary
    manifest["report_return_code"] = 0
    manifest["artifacts"]["report"] = repo_rel(root, report_dir)
    manifest["artifacts"]["summary"] = repo_rel(root, summary_path)
    manifest["artifacts"]["coverage_details_raw"] = repo_rel(root, raw_details_path)
    manifest["artifacts"]["coverage_details"] = repo_rel(root, details_path)
    manifest["artifacts"]["policy_application"] = repo_rel(root, application_path)
    write_json(manifest_path, manifest)
    if not threshold_met:
        with log_path.open("a", encoding="utf-8") as log:
            if not compatibility_threshold_met:
                log.write(f"# COVERAGE THRESHOLD: {total_percent} < {threshold}\n")
            for outcome in details.thresholds:
                if not outcome.get("met"):
                    log.write(
                        "# COVERAGE THRESHOLD: "
                        f"{outcome.get('id')} metric={outcome.get('metric_family')} "
                        f"actual={outcome.get('actual_percent')} "
                        f"minimum={outcome.get('minimum_percent')} "
                        f"unclassified={outcome.get('unclassified_points')}\n"
                    )
        return 1
    return 0


def clean_stage(stage: dict[str, Any], root: Path, ctx: dict[str, str], dry_run: bool) -> int:
    for value in as_str_list(stage.get("paths"), "clean.paths"):
        path = repo_path(root, render_text(value, ctx))
        if dry_run:
            print(f"REMOVE: {path}", flush=True)
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
    return 0


def _repo_or_dut_path(root: Path, flow: Flow, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    repo_candidate = root / path
    if repo_candidate.exists():
        return repo_candidate
    return flow.path.parent / path


def formal_run_stage(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str | None,
    args: argparse.Namespace,
    tool: str,
    simulators: dict[str, Any],
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
    if item is None:
        raise ConfigError("formal_run stage requires a formal task item")
    formal = sim_cfg.get("formal", {})
    if not isinstance(formal, dict):
        raise ConfigError(f"{flow.path}: [formal] must be a table")
    apps = formal.get("apps", {})
    if not isinstance(apps, dict):
        raise ConfigError(f"{flow.path}: [formal.apps] must be a table")
    test = catalog.tests.get(item)
    app_name = args.app or (test.module if test else item)
    app = apps.get(app_name)
    if not isinstance(app, dict):
        raise ConfigError(f"{flow.path}: formal app `{app_name}` is not defined")
    tool_cfg = app.get(tool)
    if not isinstance(tool_cfg, dict):
        default_tool = str(app.get("default_tool", tool))
        tool_cfg = app.get(default_tool) if isinstance(app.get(default_tool), dict) else None
        if tool_cfg is None:
            raise ConfigError(f"{flow.path}: formal app `{app_name}` has no `{tool}` backend")
        tool = default_tool
    sim_tool = simulators.get(tool, {})
    binary = str(sim_tool.get("binary", tool)) if isinstance(sim_tool, dict) else tool
    cwd = _repo_or_dut_path(root, flow, str(tool_cfg.get("cwd", ".")))
    script = str(tool_cfg.get("script", "")).strip()
    argv = [binary]
    argv += as_str_list(tool_cfg.get("args"), f"formal.apps.{app_name}.{tool}.args")
    if args.proof_depth is not None:
        argv += ["--proof-depth", str(args.proof_depth)]
    if script:
        argv.append(script)
    argv += args.formal_arg or []
    console_from_args(args).artifact("formal_app", f"{app_name} ({tool})")
    return run_subprocess(argv, root, log_path, args.dry_run, script_path, env_path, args.quiet, cwd=cwd, verbose=args.verbose, timeout_sec=args.timeout)


def run_stage(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    stage_name: str,
    item: str | None,
    args: argparse.Namespace,
    tool: str,
    run_dir: Path,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    nest: bool = False,
    attempt: int = 0,
    seed_override: int | None = None,
) -> StageResult:
    setattr(args, "_simulators", simulators)
    stage = flow_stages(flow)[stage_name]
    kind = str(stage.get("kind", ""))
    seed = seed_override if seed_override is not None else (seed_for_item(catalog, sim_cfg, args, item) if item else as_int(args.seed, "seed") or 1)
    stage_dir = artifact_root(run_dir, stage_name, item, seed=seed, attempt=attempt, nest=nest)
    if stage_name in {"c_compile", "formal"}:
        stage_dir = artifact_root(run_dir, stage_name, None)
    target_name = _target_name(sim_cfg)
    target_scoped_stage = (
        item is None
        and stage_name in {"flist", "hdl_compile", "elaborate"}
        and bool(getattr(args, "_multi_target_run", False))
    )
    stage_suffix = f"{stage_name}.{target_name}" if target_scoped_stage else stage_name
    log_path = stage_dir / "logs" / (f"{item}.log" if item else f"{stage_suffix}.log")
    script_path = stage_dir / "scripts" / f"{stage_suffix}{'.' + item if item else ''}.sh"
    env_path = stage_dir / "env" / f"{stage_suffix}.env"
    ctx = {
        "flow": flow.name,
        "kind": flow.kind,
        "framework": flow.framework,
        "tool": tool,
        "executor": "local",
        "target": target_name,
        "item": item or "",
        "seed": str(seed),
        # Keep `jobs` as a template alias for existing configs while exposing the
        # clearer `sim_jobs` name to new stage templates.
        "jobs": str(args.sim_jobs),
        "sim_jobs": str(args.sim_jobs),
        "run_dir": str(run_dir),
        "repo_root": str(root),
        "waves": str(_wave_format(args, tool) or ""),
    }

    console = console_from_args(args)
    suppress_leaf_ui = compact_leaf_ui(args, stage_name, item)
    ui_suppression = console.suppress(suppress_leaf_ui)
    ui_suppression.__enter__()
    dry_run_sink = None
    stdout_redirect = None
    stderr_redirect = None
    if args.quiet and args.dry_run:
        dry_run_sink = open(os.devnull, "w", encoding="utf-8")
        stdout_redirect = redirect_stdout(dry_run_sink)
        stderr_redirect = redirect_stderr(dry_run_sink)
        stdout_redirect.__enter__()
        stderr_redirect.__enter__()
    target_for_ui = target_name if target_scoped_stage else None
    console.stage_header(
        stage=stage_name,
        item=item,
        seed=seed if item else None,
        target=target_for_ui,
        log=repo_rel(root, log_path),
    )

    started_at = datetime.now(UTC)
    started = time.monotonic()
    metadata: dict[str, Any] = {}
    if item is not None:
        metadata["seed"] = seed
        metadata["attempt"] = attempt
        metadata["debug_only"] = bool(getattr(args, "_wave_debug_rerun", False))
    if stage_name in {"flist", "hdl_compile", "elaborate", "sim", "regress"}:
        metadata["target"] = target_name
    try:
        if kind == "noop":
            note = str(stage.get("note", "no operation"))
            console.event("note", note)
            write_script(script_path, root, ["echo", note], args.dry_run)
            write_env_snapshot(env_path, os.environ, args.dry_run)
            if not args.dry_run:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(note + "\n", encoding="utf-8")
            rc = 0
        elif kind == "coverage_merge":
            rc = coverage_stage(flow, root, sim_cfg, tool, run_dir, "merge", args, log_path, script_path, env_path, args.quiet)
        elif kind == "coverage_report":
            rc = coverage_stage(flow, root, sim_cfg, tool, run_dir, "report", args, log_path, script_path, env_path, args.quiet)
        elif kind == "clean":
            rc = clean_stage(stage, root, ctx, args.dry_run)
        elif kind == "c_compile":
            rc = c_compile_stage(flow, root, sim_cfg, catalog, item, args, tool, stage_dir, log_path, script_path, env_path, seed)
        elif kind == "formal_run":
            rc = formal_run_stage(flow, root, sim_cfg, catalog, item, args, tool, simulators, log_path, script_path, env_path)
        elif kind in {"bender_filelist", "verilator_filelist"}:
            # The `native-cocotb` profile maps the logical `flist` stage to `bender_filelist` for
            # every tool (VCS runs via cocotb's classic make, not the dedicated vcs_* stages), so the
            # tool-dependent stub ordering has to key off the actual target tool here.
            rc = generate_filelist(
                flow, root, sim_cfg, args.dry_run, log_path, script_path, env_path, args.quiet,
                verbose=args.verbose, tool=tool,
            )
        elif kind == "verilator_compile":
            if tool != "verilator":
                note = f"standalone Verilator compile skipped for tool `{tool}`; cocotb_sim builds the selected simulator model"
                console.event("note", note)
                write_script(script_path, root, ["echo", note], args.dry_run)
                write_env_snapshot(env_path, os.environ, args.dry_run)
                if not args.dry_run:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(note + "\n", encoding="utf-8")
                rc = 0
            else:
                rc = generate_filelist(flow, root, sim_cfg, args.dry_run, log_path, script_path, env_path, args.quiet, verbose=args.verbose)
                if rc == 0:
                    rc = verilator_compile(flow, root, sim_cfg, stage_name, tool, args, log_path, script_path, env_path)
        elif kind == "cocotb_build":
            rc = cocotb_build(
                flow,
                root,
                sim_cfg,
                catalog,
                args,
                tool,
                stage_dir,
                log_path,
                script_path,
                env_path,
            )
            metadata["target_build"] = _cocotb_target_build_metadata(
                _cocotb_build_info(flow, root, sim_cfg, args, tool),
                tool,
            )
        elif kind in {"cocotb_verilator", "cocotb_sim"}:
            if item is None:
                raise ConfigError(f"{kind} stage requires a test item")
            rc = cocotb_sim(flow, root, sim_cfg, catalog, item, args, tool, stage_dir, log_path, script_path, env_path, seed)
            # Mirror the documented metadata shape enough for cache/debug consumers. Detailed cache
            # decisions are made inside `cocotb_sim`; this records the invariant stage-level inputs.
            metadata["build_cache"] = {
                "enabled": bool(build_cfg(flow, sim_cfg).get("options", {}).get("cache_enabled", False)),
                "rebuild": bool(args.rebuild),
            }
            metadata["target_build"] = _cocotb_target_build_metadata(
                _cocotb_build_info(flow, root, sim_cfg, args, tool),
                tool,
            )
        elif kind == "vcs_filelist":
            rc = generate_filelist(flow, root, sim_cfg, args.dry_run, log_path, script_path, env_path, args.quiet, verbose=args.verbose, tool="vcs")
        elif kind == "vcs_analyze":
            rc = vcs_analyze(flow, root, sim_cfg, args, log_path, script_path, env_path)
        elif kind == "vcs_compile":
            rc = vcs_build(flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=True)
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "vcs_elaborate":
            rc = vcs_build(flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=False)
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "vcs_sim":
            if item is None:
                raise ConfigError("vcs_sim stage requires a test item")
            rc = vcs_sim(flow, root, sim_cfg, catalog, item, args, stage_dir, log_path, script_path, env_path, seed)
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "xrun_filelist":
            rc = generate_filelist(flow, root, sim_cfg, args.dry_run, log_path, script_path, env_path, args.quiet, verbose=args.verbose)
        elif kind == "xrun_analyze":
            rc = xcelium_analyze(flow, root, sim_cfg, args, log_path, script_path, env_path)
        elif kind == "xrun_compile":
            rc = xcelium_build(flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=True)
            info = _xcelium_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="xcelium",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "xrun_elaborate":
            rc = xcelium_build(flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=False)
            info = _xcelium_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="xcelium",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "xrun_sim":
            if item is None:
                raise ConfigError("xrun_sim stage requires a test item")
            rc = xcelium_sim(flow, root, sim_cfg, catalog, item, args, stage_dir, log_path, script_path, env_path, seed)
            info = _xcelium_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="xcelium",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        else:
            raise ConfigError(f"{flow.path}: unsupported native stage kind `{kind}`")

        if (
            stage_name in {"sim", "regress"}
            and item is not None
            and args.cov
        ):
            tool_cov = coverage_cfg(sim_cfg).get(tool, {})
            if not isinstance(tool_cov, dict):
                raise ConfigError(f"coverage.{tool} must be a table")
            native_coverage = coverage_artifact_path(tool_cov, stage_dir / "coverage")
            target_build = metadata.get("target_build")
            fingerprint = (
                target_build.get("fingerprint")
                if isinstance(target_build, dict)
                else None
            )
            metadata["coverage"] = {
                "requested": True,
                "path": repo_rel(root, native_coverage),
                "tool": tool,
                "target": target_name,
                "build_fingerprint": fingerprint,
                "supported_metrics": _coverage_supported_metrics(args, tool),
                "debug_only": bool(getattr(args, "_wave_debug_rerun", False)),
            }
            if not args.dry_run and rc == 0 and not artifact_ready(native_coverage):
                raise CoverageError(
                    f"{tool} simulation completed without the expected coverage artifact: "
                    f"{native_coverage}"
                )

        if (
            stage_name in {"hdl_compile", "elaborate"}
            and args.cov
            and tool == "vcs"
        ):
            vcs_cov = coverage_cfg(sim_cfg).get("vcs", {})
            if isinstance(vcs_cov, dict):
                design_db = _coverage_design_db(flow, root, sim_cfg, vcs_cov, args)
                if design_db is not None:
                    metadata["coverage"] = {
                        "requested": True,
                        "design_db": repo_rel(root, design_db),
                        "tool": tool,
                        "target": target_name,
                    }
                    if not args.dry_run and rc == 0 and not artifact_ready(design_db):
                        raise CoverageError(
                            "VCS build completed without the expected design coverage "
                            f"database: {design_db}"
                        )
        status = "PASS" if rc == 0 else "FAIL"
        reason = "process completed successfully" if rc == 0 else f"process exited {rc}"
        bucket_kind = FAILURE_BUCKET_BY_STAGE.get(stage_name, "tool_error")
        if rc != 0 and stage_name == "cov_report" and log_path.is_file() and "COVERAGE THRESHOLD:" in log_path.read_text(encoding="utf-8", errors="replace"):
            bucket_kind = "coverage_threshold"
            reason = "coverage threshold not met"
        buckets = None if rc == 0 else [{"kind": bucket_kind, "signature": reason, "count": 1, "examples": [repo_rel(root, log_path)]}]
        parser = None
        if stage_name in {"sim", "regress"} and not args.dry_run:
            decision = parse_stage_result(
                flow=flow,
                tool=tool,
                policies=policies,
                simulators=simulators,
                root=root,
                log_path=log_path,
                results_dir=stage_dir / "results",
                return_code=rc,
            )
            status = decision.status
            reason = decision.reason
            buckets = decision.failure_buckets or buckets
            if buckets:
                for bucket in buckets:
                    examples = bucket.setdefault("examples", [])
                    rel_log = repo_rel(root, log_path)
                    if rel_log and rel_log not in examples:
                        examples.append(rel_log)
            parser = decision.parser
    except StageTimeoutError as exc:
        rc = 124
        status = "TIMEOUT"
        reason = str(exc)
        buckets = [{"kind": "timeout", "signature": reason[:120], "count": 1, "examples": [repo_rel(root, log_path)]}]
        parser = None
        console.event("error", reason)
    except Exception as exc:
        rc = 2
        status = "ERROR"
        reason = str(exc)
        # Cause-based bucketing: a config problem is a config_error no matter which stage it
        # surfaced in; only unclassified process failures fall back to the per-stage default.
        bucket_kind = "config_error" if isinstance(exc, ConfigError) else FAILURE_BUCKET_BY_STAGE.get(stage_name, "tool_error")
        buckets = [{"kind": bucket_kind, "signature": reason[:120], "count": 1, "examples": [repo_rel(root, log_path)]}]
        parser = None
        console.event("error", reason)

    ended_at = datetime.now(UTC)
    duration_sec = time.monotonic() - started
    artifacts: dict[str, Any] = {
        "script": repo_rel(root, script_path),
        "env": repo_rel(root, env_path),
    }
    coverage_meta = metadata.get("coverage")
    if isinstance(coverage_meta, dict):
        if coverage_meta.get("path"):
            artifacts["coverage"] = coverage_meta["path"]
        if coverage_meta.get("design_db"):
            artifacts["coverage_design"] = coverage_meta["design_db"]
    if stage_name in {"cov_merge", "cov_report"}:
        manifest_path = run_dir / "cov" / "coverage.json"
        report_dir = run_dir / "cov" / "report"
        summary_path = report_dir / "summary.json"
        details_path = report_dir / "coverage-details.json"
        raw_details_path = report_dir / "coverage-details.raw.json"
        application_path = report_dir / "policy-application.json"
        if manifest_path.is_file():
            artifacts["coverage_manifest"] = repo_rel(root, manifest_path)
            try:
                manifest = load_manifest(manifest_path)
            except CoverageError:
                manifest = {}
            manifest_artifacts = (
                manifest.get("artifacts")
                if isinstance(manifest.get("artifacts"), dict)
                else {}
            )
            if manifest_artifacts.get("merged"):
                artifacts["coverage"] = manifest_artifacts["merged"]
            inputs = manifest.get("inputs")
            if isinstance(inputs, list):
                artifacts["coverage_inputs"] = [
                    entry.get("path")
                    for entry in inputs
                    if isinstance(entry, dict) and entry.get("path")
                ]
            metadata["coverage"] = {
                "backend": manifest.get("backend"),
                "parser": manifest.get("parser"),
                "tool_version": manifest.get("tool_version"),
                "target": manifest.get("target"),
                "build_fingerprint": manifest.get("build_fingerprint"),
                "supported_metrics": manifest.get("supported_metrics", []),
            }
        if report_dir.is_dir():
            artifacts["coverage_report"] = repo_rel(root, report_dir)
        if summary_path.is_file():
            artifacts["coverage_summary"] = repo_rel(root, summary_path)
        if details_path.is_file():
            artifacts["coverage_details"] = repo_rel(root, details_path)
        if raw_details_path.is_file():
            artifacts["coverage_details_raw"] = repo_rel(root, raw_details_path)
        if application_path.is_file():
            artifacts["coverage_policy_application"] = repo_rel(
                root, application_path
            )
    if stage_name in {"sim", "regress"} and item and wave_active(args):
        wave_format = _wave_format(args, tool)
        waves_dir = stage_dir / "waves"
        range_info = _wave_range(args)
        wave_meta, wave_files, wave_dir = build_wave_metadata(
            args=args,
            root=root,
            flow_name=flow.name,
            item=item,
            seed=seed,
            tool=tool,
            wave_format=wave_format,
            waves_dir=waves_dir,
            log_path=log_path,
            script_path=script_path,
            env_path=env_path,
            result_json_path=stage_dir / "result.json",
            status=status,
            range_info=range_info,
            backend_range_supported=_backend_range_supported(tool, wave_format),
        )
        failure_time = getattr(args, "_wave_failure_time", None)
        if isinstance(failure_time, dict) and failure_time:
            wave_meta["failure_time_source"] = failure_time
        metadata["waves"] = wave_meta
        artifacts["waves"] = wave_dir
        if wave_files:
            artifacts["wave_files"] = wave_files
        if wave_meta.get("debug_context_json"):
            artifacts["wave_debug_context"] = wave_meta["debug_context_json"]
        if wave_meta.get("copied_log"):
            artifacts["wave_log"] = wave_meta["copied_log"]
    target_build = metadata.get("target_build")
    if isinstance(target_build, dict):
        if stage_name in {"hdl_compile", "elaborate"}:
            target_build["status"] = status
        else:
            target_build.setdefault("status", "PASS")
    if status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"} and not args.verbose:
        console.failure_tail(log_path)
    console.stage_result(
        stage=stage_name,
        item=item,
        target=target_for_ui,
        status=status,
        duration_sec=duration_sec,
    )
    if stderr_redirect is not None:
        stderr_redirect.__exit__(None, None, None)
    if stdout_redirect is not None:
        stdout_redirect.__exit__(None, None, None)
    if dry_run_sink is not None:
        dry_run_sink.close()
    ui_suppression.__exit__(None, None, None)
    return StageResult(
        stage=stage_name,
        item=item,
        status=status,
        return_code=rc,
        duration_sec=duration_sec,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        log=repo_rel(root, log_path),
        artifacts=artifacts,
        failure_buckets=buckets,
        reason=reason,
        parser=parser,
        metadata=metadata,
        target=target_name if stage_name in {"flist", "hdl_compile", "elaborate", "sim", "regress"} else None,
    )
