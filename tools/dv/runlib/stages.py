# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .buildcache import (
    apply_option_env,
    build_fingerprint,
    build_options_cfg,
    build_vcs_cfg,
    build_verilator_cfg,
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
    formal_template_placeholders,
    render_formal_argv,
    selected_compile_target,
    selected_run_mode,
    selected_run_target,
    sim_global_args,
    target_flags,
    validate_formal_argv_template,
)
from .coverage import (
    CANONICAL_METRICS,
    CoverageError,
    artifact_ready,
    coverage_artifact_path,
    discover_coverage_inputs,
    load_manifest,
    new_manifest,
    render_tokens,
    write_json,
)
from .coverage_closure import (
    coverage_backend,
    coverage_fail_under,
    coverage_merged_name,
    coverage_parser_name,
    coverage_run_paths,
    grade_coverage_run,
    parse_coverage_run,
)
from .coverage_policy import (
    CoveragePolicy,
    load_coverage_policy,
    native_policy_args,
    native_policy_manifest,
)
from .formal import grade_formal_stage
from .junit import ensure_leaf_junit
from .logparse import parse_stage_result, xunit_failure_messages
from .models import ConfigError, Flow, StageResult, StageTimeoutError, TestCatalog, TestEntry
from .paths import repo_path, repo_rel
from .site import ToolLaunch, launch_argv, launch_env, tool_launch
from .ui import Console
from .waves import (
    build_wave_metadata,
    format_time_ps,
    require_verdi_home,
    resolve_verdi_home,
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

# Adopters set the OCAH names; these are the vendor aliases ocah_vendor_defines.svh
# derives. Flows expand them onto the command line so tools without a force-include
# still see the vendor spelling. Do not emit VERILATOR / TARGET_VERILATOR from Bender.
OCAH_VENDOR_DEFINE_ALIASES: dict[str, tuple[str, ...]] = {
    "SYNTHESIS": ("TARGET_SYNTHESIS",),
    "SIMULATION": ("ABR_SIMULATION",),
    "VERILATOR": ("TARGET_VERILATOR",),
    "XSIM": ("TARGET_XSIM",),
}


def _ocah_define_token(item: str) -> str | None:
    s = item.strip()
    if s.startswith("+define+"):
        return s[len("+define+") :].split("=", 1)[0]
    if s.startswith("-D"):
        rest = s[2:].lstrip()
        return rest.split("=", 1)[0] if rest else None
    if not s or s.startswith("-") or s.startswith("+"):
        return None
    return s.split("=", 1)[0]


def expand_ocah_vendor_define_aliases(items: list[str]) -> list[str]:
    """Append vendor aliases for any OCAH view name already present in *items*.

    *items* are bare ``NAME`` / ``NAME=value`` define entries or ``+define+`` /
    ``-D`` fragments mixed with other flags. Each alias is emitted in the same
    form as the first source item that triggered it.
    """
    present: set[str] = set()
    plusdefine = False
    dash_d = False
    for item in items:
        tok = _ocah_define_token(item)
        if tok:
            present.add(tok)
        stripped = item.strip()
        if stripped.startswith("+define+"):
            plusdefine = True
        elif stripped.startswith("-D"):
            dash_d = True
    extra: list[str] = []
    for src, aliases in OCAH_VENDOR_DEFINE_ALIASES.items():
        if src not in present:
            continue
        src_form_plus = plusdefine
        src_form_dash = dash_d and not plusdefine
        for alias in aliases:
            if alias in present:
                continue
            if src_form_plus:
                extra.append(f"+define+{alias}")
            elif src_form_dash:
                extra.append(f"-D{alias}")
            else:
                extra.append(alias)
            present.add(alias)
    return [*items, *extra]


_STAGE_CANCELLATION = threading.Event()
_ACTIVE_SUBPROCESS_LOCK = threading.Lock()
_ACTIVE_SUBPROCESSES: set[subprocess.Popen[bytes]] = set()


def render_text(text: str, ctx: dict[str, str]) -> str:
    rendered = text
    for key, value in ctx.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def required_path(cfg: dict[str, Any], key: str, section: str, where: str) -> str:
    """Return a required build-output path from `cfg`, or fail loud.

    Build/run output directories are per-DUT policy and must be declared in the flow's sim_cfg;
    the runner never invents one. A missing path is a config error, as it is for
    ``[build].top_module``.
    """
    value = cfg.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{where}: [{section}].{key} is required and must be a non-empty string (declare it in your sim_cfg)"
        )
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


def _bender_filelist_sources(root: Path, build: dict[str, Any]) -> list[Path]:
    """The source files named inside the generated ``[build].bender_filelist``.

    The bender filelist holds one path per line, plus ``//`` comments and the
    ``+incdir+`` / ``+define+`` options `generate_filelist` passes through. Only the plain
    paths are source files, so option and comment lines are skipped. Order is preserved and
    duplicates are dropped. An empty list is returned when the DUT declares no bender
    filelist or the file is not generated yet.
    """
    rel = str(build.get("bender_filelist") or "").strip()
    if not rel:
        return []
    filelist = repo_path(root, rel)
    if not filelist.is_file():
        return []
    seen: set[Path] = set()
    sources: list[Path] = []
    for line in filelist.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = line.strip()
        if not entry or entry.startswith(("//", "#", "+", "-")):
            continue
        path = repo_path(root, entry)
        if path not in seen:
            seen.add(path)
            sources.append(path)
    return sources


def _bender_sources_fingerprint(root: Path, build: dict[str, Any]) -> list[str]:
    """One digest over the CONTENT of every file the bender filelist names.

    ``build_fingerprint`` hashes the combined filelist TEXT, which names the bender filelist
    as a single ``-f`` line. That text is blind both to a path added or removed inside the
    bender filelist and to a content-only edit of a file it names, so the digest here is what
    makes vendored or DUT RTL move the build identity. Each entry contributes its
    repo-relative path (so the digest does not move when the same tree is built
    from a different checkout) and the SHA-256 of its bytes; a path that does
    not resolve contributes ``<missing>`` so a deleted file still moves the
    digest instead of failing the build.

    Cost is one read of every named source.
    """
    sources = _bender_filelist_sources(root, build)
    if not sources:
        return []
    digest = hashlib.sha256()
    for path in sources:
        digest.update((repo_rel(root, path) or str(path)).encode("utf-8"))
        digest.update(b"\0")
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return [f"bender_sources={len(sources)}:{digest.hexdigest()[:16]}"]


def _filelist_sources(root: Path, filelist: Path, seen: set[Path] | None = None) -> list[Path]:
    """Every source file a compile filelist names, following ``-f``/``-F`` includes.

    Plain lines are sources; ``+incdir+``/``+define+`` options and ``//``/``#`` comments carry
    no content of their own. An include that does not resolve contributes nothing here and is
    reported as missing by the compile itself.
    """
    if seen is None:
        seen = set()
    if not filelist.is_file() or filelist in seen:
        return []
    seen.add(filelist)
    sources: list[Path] = []
    for line in filelist.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = line.strip()
        if not entry or entry.startswith(("//", "#", "+")):
            continue
        if entry.startswith(("-f ", "-F ")):
            sources.extend(_filelist_sources(root, repo_path(root, entry[3:].strip()), seen))
            continue
        if entry.startswith("-"):
            continue
        path = repo_path(root, entry)
        if path not in seen:
            seen.add(path)
            sources.append(path)
    return sources


def _content_digest(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update((repo_rel(root, path) or str(path)).encode("utf-8"))
        digest.update(b"\0")
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _filelist_sources_fingerprint(root: Path, filelist: Path) -> list[str]:
    """One digest over the CONTENT of every source the compile filelist reaches.

    The filelist text names its sources and its ``-f`` includes by path only, so this digest
    is what moves the build identity on an edit to a testbench file, a coverage module, or a
    DUT source the Bender filelist names.
    """
    sources = _filelist_sources(root, filelist)
    if not sources:
        return []
    return [f"filelist_sources={len(sources)}:{_content_digest(root, sources)}"]


def _file_args_fingerprint(root: Path, build_args: list[str]) -> list[str]:
    """One digest over the CONTENT of every build argument that names an existing file.

    Coverage scope files and similar side inputs reach the compiler as a path, so an edit to
    one of them leaves the argument text unchanged.
    """
    files: list[Path] = []
    for arg in build_args:
        text = str(arg)
        if not text or text.startswith(("-", "+")):
            continue
        path = repo_path(root, text)
        if path.is_file() and path not in files:
            files.append(path)
    if not files:
        return []
    return [f"file_args={len(files)}:{_content_digest(root, files)}"]


BUILD_RECORD_NAME = "build_record.json"


def _build_record_decision(
    record_path: Path, fingerprint: str, requested: bool
) -> tuple[bool, str]:
    """Whether the cocotb build must run clean, and why.

    cocotb's runner rebuilds only when a listed source is newer than the model, and this
    flow lists no sources (they arrive through the filelist), so an existing model is
    otherwise reused whatever changed. The record written after each build carries the
    fingerprint of the inputs that produced the model; a different fingerprint, or no
    record beside an existing model, forces the clean build.
    """
    if requested:
        return True, "requested"
    if not record_path.parent.is_dir():
        return False, ""
    try:
        recorded = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True, "no build record"
    if not isinstance(recorded, dict) or recorded.get("fingerprint") != fingerprint:
        return True, "inputs changed"
    return False, ""


def _write_build_record(
    record_path: Path, fingerprint: str, tool_version: str, dry_run: bool
) -> None:
    payload = {
        "fingerprint": fingerprint,
        "tool_version": tool_version,
        "written_at": datetime.now(UTC).isoformat(),
    }
    write_text_file(record_path, json.dumps(payload, indent=2) + "\n", dry_run)


def _verilator_public_scope_fingerprint(root: Path, build: dict[str, Any]) -> list[str]:
    scope = str(build_verilator_cfg(build).get("public_scope") or "").strip()
    if not scope:
        return []
    path = repo_path(root, scope)
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "<missing>"
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


def grade_expected_fail(
    status: str,
    reason: str,
    buckets: list[dict[str, Any]] | None,
    expect_fail: str,
    *,
    observed_failures: list[str] | None = None,
    expect_fail_match: str | None = None,
) -> tuple[str, str, list[dict[str, Any]] | None, dict[str, Any]]:
    """Grade a leaf whose testlist entry carries `expect_fail`.

    An observed FAIL is the recorded outcome and grades PASS -- unless the entry also carries
    `expect_fail_match` and no observed failure message matches it, in which case the leaf
    failed for a reason other than the recorded one and grades FAIL in the
    `expected_fail_mismatch` bucket. An observed PASS means the defect the entry records is
    no longer there, and grades FAIL so the entry cannot outlive its reason. ERROR, TIMEOUT
    and UNKNOWN are not the recorded failure -- the leaf proved nothing either way -- and
    keep their status. The returned record goes into the leaf metadata under `expected_fail`
    with the observed status, reason, failure messages and the parser's failure buckets.
    """
    failures = list(observed_failures or [])
    record: dict[str, Any] = {
        "reason": expect_fail,
        "observed_status": status,
        "observed_reason": reason,
        "observed_failures": failures,
        "observed_buckets": [
            {"kind": bucket.get("kind"), "signature": bucket.get("signature")}
            for bucket in buckets or []
        ],
    }
    if expect_fail_match is not None:
        record["match"] = expect_fail_match
    if status == "FAIL":
        if expect_fail_match is not None and not any(
            re.search(expect_fail_match, message) for message in failures
        ):
            first = failures[0] if failures else "no failure message recorded"
            graded_reason = (
                f"expected to fail ({expect_fail}) but failed for another reason: {first}"
            )
            bucket = {
                "kind": "expected_fail_mismatch",
                "signature": graded_reason[:120],
                "count": 1,
                "examples": [],
            }
            return "FAIL", graded_reason, [bucket], record
        return "PASS", f"expected_fail: {expect_fail}", None, record
    if status == "PASS":
        graded_reason = (
            f"expected to fail ({expect_fail}) but passed: the defect is gone, move the test "
            "into its owning feature testlist and drop expect_fail"
        )
        bucket = {
            "kind": "expected_fail_passed",
            "signature": graded_reason[:120],
            "count": 1,
            "examples": [],
        }
        return "FAIL", graded_reason, [bucket], record
    return status, reason, buckets, record


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


def _stamp_provenance(
    root: Path,
    log_path: Path,
    metadata: dict[str, Any],
    *,
    fingerprint: str | None,
    filelist: Path | None,
    dry_run: bool,
    sim_args: list[str] | None = None,
    cwd: Path | None = None,
) -> None:
    """Bind a per-test log to the sources, build and images that produced it.

    Records the commit, the dirty flag, the build fingerprint and the filelist
    digest in the stage metadata (so they reach ``result.json``) and appends the
    same facts as one ``PROVENANCE`` line at the end of the per-test log, so the
    log on its own names the build it came from.

    ``sim_args`` are the simulator arguments the leaf ran with. Every
    ``+key=value`` whose value names a regular file (firmware, ROM, eFuse and
    shadow-register images) is digested into ``provenance.images`` and written
    as one ``FW-PROVENANCE`` line after the ``PROVENANCE`` line, so the log
    names the bytes the simulation loaded. ``cwd`` is the directory the
    simulator ran in, which is how it resolves a relative image path.
    """
    from .results import git_info

    git = git_info(root)
    flist_sha = None
    if filelist is not None and filelist.is_file():
        flist_sha = hashlib.sha256(filelist.read_bytes()).hexdigest()[:16]
    prov: dict[str, Any] = {
        "commit": git.get("commit", ""),
        "branch": git.get("branch", ""),
        "dirty": git.get("dirty", ""),
        "build_fingerprint": fingerprint or "",
        "filelist": repo_rel(root, filelist) if filelist is not None else "",
        "filelist_sha256": flist_sha or "",
    }
    images = _image_provenance(root, sim_args or [], cwd=cwd)
    prov["images"] = images
    metadata["provenance"] = prov
    if dry_run or not log_path.is_file():
        return
    line = "PROVENANCE " + " ".join(
        f"{key}={value}" for key, value in prov.items() if key != "images" and value != ""
    )
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n{line}\n")
        for key, image in images.items():
            log.write(f"FW-PROVENANCE {key}={image['path']} sha256={image['sha256']}\n")


def _image_provenance(
    root: Path, sim_args: list[str], *, cwd: Path | None = None
) -> dict[str, dict[str, str]]:
    """Digest every ``+key=value`` simulator argument whose value is a regular file.

    Returns ``{key: {"path", "sha256"}}`` keyed by the plusarg name without its
    ``+``. The path is repo-relative when the file sits inside the checkout and
    absolute otherwise; the digest covers the whole file. A relative value is
    resolved the way the simulator resolves it, against ``cwd`` first and the
    repository root second. Arguments that are not ``+key=value``, whose value
    is empty, or whose value is not an existing regular file contribute nothing.
    """
    images: dict[str, dict[str, str]] = {}
    for arg in sim_args:
        key = _plusarg_key(arg)
        if key is None:
            continue
        value = arg.split("=", 1)[1]
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            for base in (cwd, root):
                if base is not None and (base / candidate).is_file():
                    candidate = base / candidate
                    break
        if not candidate.is_file():
            continue
        images[key.lstrip("+")] = {
            "path": repo_rel(root, candidate) or str(candidate),
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        }
    return images


def _sim_test_args(
    sim_cfg: dict[str, Any],
    run_mode: dict[str, Any],
    test: TestEntry,
    args: argparse.Namespace,
    seed: int,
    root: Path,
) -> list[str]:
    """Return the config- and CLI-owned simulator arguments of one leaf.

    Every sim site passes them in this order: `sim_global_args`, the rendered
    run-mode and test args, then `--sim-arg` and `--plusarg`. Sharing the list
    between the launch and the provenance stamp keeps the digested images equal
    to the ones the simulator was handed.
    """
    return [
        *sim_global_args(sim_cfg),
        *_render_run_test_args(run_mode, test, seed, root),
        *(args.sim_arg or []),
        *(args.plusarg or []),
    ]


def _cocotb_target_build_metadata(
    info: dict[str, Any], tool: str, *, status: str | None = None
) -> dict[str, Any]:
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
    if tool == "vcs" and wave_format in {"fsdb", "vpd"}:
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
    lines.extend(
        [
            f"database -open waves -into {db_path} -event -default",
            "probe -create [scope -tops] -all -depth to_cells -database waves",
        ]
    )
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


def _vcs_wave_ucli(
    *,
    ucli_path: Path,
    waves_dir: Path,
    item: str,
    top: str,
    wave_format: str,
    range_info: dict[str, Any],
    dry_run: bool,
) -> None:
    """Generated UCLI script that starts the VCS dump (fsdb/vpd) without testbench hooks.

    VCS never begins dumping on its own: `+fsdbfile+`/`+vpdfile=` only name a dump that a
    `$fsdbDumpvars`/`$vcdpluson` call would open. Driving the dump from `simv -ucli -i <script>`
    needs only `-debug_access` at compile (already present in both the cocotb make flow and the
    wave-enabled UVM build) and works for any testbench. UCLI exits on its own at
    end-of-simulation/`$finish`, so the script composes with cocotb's shutdown.
    """
    dump_type = "FSDB" if wave_format == "fsdb" else "VPD"
    db_path = waves_dir / f"{item}.{wave_format}"
    start_ps = range_info.get("start_ps")
    end_ps = range_info.get("end_ps")
    add_opts = "-fsdb_opt +all" if wave_format == "fsdb" else "-aggregates"
    lines = [
        "# Generated by run_dv.py for waveform capture.",
    ]
    if start_ps is not None and start_ps > 0:
        lines.append(f"run {format_time_ps(start_ps)}")
    # A dump-setup failure (e.g. FSDB writer not loadable) must not abort the -i script:
    # degrade to a normal wave-less run; the launcher warns when no wave file appears.
    lines += [
        "if {[catch {",
        f"    set fid [dump -file {db_path} -type {dump_type}]",
        f"    dump -add {top} -depth 0 -fid $fid {add_opts}",
        "} err]} {",
        '    puts "run_dv: waveform dump setup FAILED: $err"',
        "    run",
        "} else {",
    ]
    if end_ps is not None:
        duration = max(0, int(end_ps) - int(start_ps or 0))
        if duration > 0:
            lines.append(f"    run {format_time_ps(duration)}")
        lines.append("    catch {dump -close}")
    lines += [
        "    run",
        "}",
    ]
    write_text_file(ucli_path, "\n".join(lines) + "\n", dry_run)


def _vcs_wave_env(env: dict[str, str], wave_format: str, dry_run: bool) -> dict[str, str]:
    """Ensure the simv child sees a VERDI_HOME that really ships the FSDB writer.

    An inherited VERDI_HOME can be stale (validated against libnovas.so), so the resolved,
    validated home always wins; vpd needs nothing.
    """
    if wave_format != "fsdb":
        return env
    home = resolve_verdi_home() if dry_run else require_verdi_home("vcs", wave_format)
    if home and env.get("VERDI_HOME") != home:
        env = dict(env)
        env["VERDI_HOME"] = home
    return env


def item_artifact_dir(
    run_dir: Path, item: str, *, seed: int | None = None, attempt: int = 0, nest: bool = False
) -> Path:
    """Per-test (test-major) artifact directory.

    Single-test invocations stay flat at ``<run_dir>/<item>``. Regression/group runs always nest
    every test as ``<run_dir>/<item>/seed_<seed>/attempt_<attempt>`` so the layout is uniform.
    """
    base = run_dir / item
    if nest:
        base = base / f"seed_{seed}" / f"attempt_{attempt}"
    return base


def artifact_root(
    run_dir: Path,
    stage: str,
    item: str | None = None,
    *,
    seed: int | None = None,
    attempt: int = 0,
    nest: bool = False,
) -> Path:
    """Run-shared stages live under ``stages/<stage>/``; per-test stages are test-major."""
    if item is None:
        return run_dir / "stages" / stage
    return item_artifact_dir(run_dir, item, seed=seed, attempt=attempt, nest=nest)


def seed_for_item(
    catalog: TestCatalog, sim_cfg: dict[str, Any], args: argparse.Namespace, item: str
) -> int:
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
    return Console(
        getattr(args, "ui", "auto"),
        quiet=getattr(args, "quiet", False),
        verbose=getattr(args, "verbose", False),
    )


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


def reset_stage_cancellation() -> None:
    _STAGE_CANCELLATION.clear()


def request_stage_cancellation() -> None:
    """Stop registered stage process groups after an interrupted run."""
    _STAGE_CANCELLATION.set()
    with _ACTIVE_SUBPROCESS_LOCK:
        processes = list(_ACTIVE_SUBPROCESSES)
    if not processes:
        return
    for proc in processes:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(0.2)
    for proc in processes:
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


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
    launch: ToolLaunch | None = None,
) -> int:
    """Run ``argv`` with its output in ``log_path`` and a replay script beside it.

    ``launch`` is the site-resolved launch of the tool behind ``argv``: its launcher prefixes
    the command and its environment exports join ``env`` before the snapshot is written.
    """
    if launch is not None:
        argv = launch_argv(launch, argv)
        env = launch_env(launch, env)
    workdir = cwd or root
    if dry_run or verbose:
        print("CMD  : " + " ".join(shlex.quote(part) for part in argv), flush=True)
    write_script(script_path, workdir, argv, dry_run)
    write_env_snapshot(env_path, env or dict(os.environ), dry_run)
    if dry_run:
        return 0
    if _STAGE_CANCELLATION.is_set():
        raise RuntimeError("stage execution cancelled")
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
            # No stage reads the terminal; EOF on stdin also guarantees an interactive
            # tool prompt (e.g. simv -ucli after a script error) exits instead of hanging.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        with _ACTIVE_SUBPROCESS_LOCK:
            _ACTIVE_SUBPROCESSES.add(proc)
        try:
            assert proc.stdout is not None
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            start = time.monotonic()
            timed_out = False
            cancelled = False
            try:
                while True:
                    if _STAGE_CANCELLATION.is_set():
                        cancelled = True
                        break
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
            if cancelled:
                terminate_process_group(proc)
                raise RuntimeError("stage execution cancelled")
            if timed_out:
                terminate_process_group(proc)
                log.write(f"\n# TIMEOUT: command exceeded {timeout_sec}s and was killed\n")
                log.flush()
                raise StageTimeoutError(f"`{argv[0]}` exceeded timeout of {timeout_sec}s")
            return proc.returncode
        finally:
            with _ACTIVE_SUBPROCESS_LOCK:
                _ACTIVE_SUBPROCESSES.discard(proc)


def stage_tool_launch(args: argparse.Namespace, tool: str) -> ToolLaunch:
    """The site-resolved launch of ``tool`` from the registry run_stage attaches to ``args``."""
    simulators = getattr(args, "_simulators", None)
    return tool_launch(simulators if isinstance(simulators, dict) else {}, tool)


# The executable cocotb's Python runner probes on PATH per tool, and the runner class.
COCOTB_DEFAULT_BINARY = {"verilator": "verilator", "xcelium": "xrun", "vcs": "vcs"}
COCOTB_RUNNER_CLASS = {"verilator": "Verilator", "xcelium": "Xcelium", "vcs": "Vcs"}


def reject_cocotb_launcher(launch: ToolLaunch) -> None:
    """cocotb's Python runner starts the simulator itself, so a launcher cannot wrap it."""
    if launch.launcher:
        raise ConfigError(
            f"site `launcher` for `{launch.tool}` does not apply on the cocotb path: cocotb's "
            "Python runner starts the simulator from the runner's own process. Run run_dv.py "
            "inside the launcher's environment, or drop the launcher and keep `binary`, "
            "`extra_env`, and `setup_hook`"
        )


def _rename_commands(commands: Any, default: str, binary: str) -> list[Any]:
    renamed: list[Any] = []
    for cmd in commands:
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == default:
            renamed.append([binary, *cmd[1:]])
        else:
            renamed.append(cmd)
    return renamed


@contextmanager
def cocotb_tool_binary(tool: str, binary: str):
    """Point cocotb's runner at the site ``binary`` when it differs from the name it probes.

    Verilator's runner records the probed executable and runs it through perl; the Xcelium
    and VCS runners spell the executable into each command. The PATH probe is replaced so a
    renamed binary passes it, and the commands are renamed as they are built.
    """
    default = COCOTB_DEFAULT_BINARY.get(tool)
    if default is None or binary == default:
        yield
        return
    module = importlib.import_module("cocotb_tools.runner")
    cls = getattr(module, COCOTB_RUNNER_CLASS[tool], None)
    if cls is None:
        raise ConfigError(
            f"site binary `{binary}` for `{tool}` but no cocotb {tool} runner was found"
        )

    def probe(self: Any) -> None:
        found = shutil.which(binary)
        if found is None:
            raise SystemExit(f"ERROR: {binary} executable not found!")
        self.executable = found

    def make_wrapper(orig: Any) -> Any:
        def wrapper(self: Any) -> Any:
            return _rename_commands(orig(self), default, binary)

        return wrapper

    saved: dict[str, Any] = {}
    if tool == "verilator":
        saved["_simulator_in_path_build_only"] = cls._simulator_in_path_build_only
        cls._simulator_in_path_build_only = probe
    else:
        saved["_simulator_in_path"] = cls._simulator_in_path
        cls._simulator_in_path = probe
        for name in ("_build_command", "_test_command"):
            saved[name] = getattr(cls, name)
            setattr(cls, name, make_wrapper(saved[name]))
    try:
        yield
    finally:
        for name, original in saved.items():
            setattr(cls, name, original)


def get_cocotb_runner():
    try:
        from cocotb_tools.runner import get_runner

        return get_runner
    except ImportError as exc:
        raise ConfigError(
            "cocotb's Python runner (cocotb_tools.runner, cocotb >= 2.0) is required for "
            "cocotb stages. Launch via `python3 tools/dv/run_dv.py` so the uv-managed DV "
            f"environment provides cocotb (current interpreter: {sys.executable})"
        ) from exc


@contextmanager
def cocotb_make_jobs(jobs: int):
    """Map runlib build jobs onto the cocotb runner's generated-model make.

    cocotb's Python runner drives its generated Verilator model build through
    MAX_PARALLEL_BUILD_JOBS (default 4) and exposes no per-build jobs argument.
    The user-visible policy lives in config/CLI
    (`[build.options].build_jobs` / `--build-jobs`); this maps that value onto the constant.
    """
    patched: list[tuple[Any, int]] = []
    if jobs > 1:
        try:
            from cocotb_tools import runner as cocotb_runner
        except ImportError:
            pass
        else:
            if hasattr(cocotb_runner, "MAX_PARALLEL_BUILD_JOBS"):
                patched.append((cocotb_runner, int(cocotb_runner.MAX_PARALLEL_BUILD_JOBS)))
                cocotb_runner.MAX_PARALLEL_BUILD_JOBS = jobs
    try:
        yield
    finally:
        for module, old_value in patched:
            module.MAX_PARALLEL_BUILD_JOBS = old_value


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
    tb top, leaving the DUT fabric optimisable.

    This wraps ``Verilator._build_command`` at runtime rather than editing the
    installed ``cocotb_tools/runner.py``, which ``uv sync`` recreates.
    """
    if not vlt_path:
        yield
        return
    if not Path(vlt_path).is_file():
        raise ConfigError(f"configured Verilator public_scope file does not exist: {vlt_path}")
    patched: list[tuple[Any, Any]] = []
    try:
        module = importlib.import_module("cocotb_tools.runner")
    except ImportError:
        module = None
    cls = getattr(module, "Verilator", None)
    original = getattr(cls, "_build_command", None)
    if cls is not None and original is not None:

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
        raise ConfigError(
            "configured Verilator public_scope but no cocotb Verilator runner was patched"
        )
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

    # `build.exclude_files` names sources the bender graph pulls in that this checkout cannot
    # compile; a filelist line containing any of them is dropped after generation.
    exclude_files = as_str_list(build.get("exclude_files"), "build.exclude_files")

    checkout_cmd = ["bender", "checkout"]
    flist_cmd = ["bender", "script", "flist-plus", *target_args]
    if dry_run or verbose:
        print("CMD  : " + " ".join(shlex.quote(part) for part in checkout_cmd), flush=True)
        print(
            "CMD  : " + " ".join(shlex.quote(part) for part in flist_cmd) + f" > {bender_out}",
            flush=True,
        )
        if exclude_files:
            print(
                "NOTE : drop from filelist (build.exclude_files): " + ", ".join(exclude_files),
                flush=True,
            )

    script_body = "#!/usr/bin/env bash\nset -euo pipefail\n"
    script_body += "cd " + shlex.quote(str(root)) + "\n"
    script_body += " ".join(shlex.quote(part) for part in checkout_cmd) + "\n"
    script_body += (
        " ".join(shlex.quote(part) for part in flist_cmd)
        + " > "
        + shlex.quote(str(bender_out))
        + "\n"
    )
    write_text_file(script_path, script_body, dry_run)
    write_env_snapshot(env_path, os.environ, dry_run)
    if not dry_run:
        script_path.chmod(0o755)
        bender_out.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            log.write("# cmd: " + " ".join(shlex.quote(part) for part in checkout_cmd) + "\n")
            proc = subprocess.run(
                checkout_cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            log.write(proc.stdout)
            if verbose and not quiet:
                print(proc.stdout, end="")
            if proc.returncode:
                return proc.returncode

            log.write(
                "# cmd: " + " ".join(shlex.quote(part) for part in flist_cmd) + f" > {bender_out}\n"
            )
            with bender_out.open("w", encoding="utf-8") as handle:
                proc = subprocess.run(
                    flist_cmd, cwd=root, stdout=handle, stderr=subprocess.PIPE, text=True
                )
            log.write(proc.stderr)
            if verbose and not quiet:
                print(proc.stderr, end="")
            if proc.returncode:
                return proc.returncode

            # Drop the sources named in build.exclude_files from the generated bender filelist
            # before it feeds the compile (substring match per line).
            if exclude_files and bender_out.exists():
                kept: list[str] = []
                for line in bender_out.read_text(encoding="utf-8").splitlines():
                    if any(pat in line for pat in exclude_files):
                        log.write(f"# excluded (build.exclude_files): {line}\n")
                    else:
                        kept.append(line)
                bender_out.write_text("\n".join(kept) + "\n", encoding="utf-8")

    incdirs = [
        repo_path(root, "hw/common/defs"),
        *[
            repo_path(root, value)
            for value in as_str_list(build.get("incdirs"), "build.incdirs")
            if value != "hw/common/defs"
        ],
    ]
    # `stubs` are DUT-local OVERRIDE sources that replace the real RTL for a module. `sources` are
    # ADDITIVE tb components (e.g. SEP's mem responders) that may reference DUT package types, so they
    # go AFTER the bender filelist where those packages are already declared.
    stubs = [repo_path(root, value) for value in as_str_list(build.get("stubs"), "build.stubs")]
    sources = [
        repo_path(root, value) for value in as_str_list(build.get("sources"), "build.sources")
    ]

    # Stub selection/placement is tool-dependent, because "which duplicate module definition wins"
    # differs and because some stubs shadow real RTL that IS present in the bender graph:
    #   * Verilator (-Wno-MODDUP, FIRST-wins): keep ALL stubs and emit them BEFORE the bender
    #     filelist so they override the real RTL. The stubs exist to dodge Verilator RTL-codegen
    #     defects, so they MUST win here.
    #   * VCS (LAST-wins): a stub that also has real RTL in the bender graph would OVERRIDE it, and
    #     a checked-in stub whose port list lags the real RTL binds silently and elaboration fails
    #     with undefined-port errors. So for VCS keep ONLY stubs that have NO real counterpart in
    #     the bender graph and emit them AFTER the bender filelist, where the DUT packages they
    #     reference are already declared. Everything with real RTL compiles from the bender graph.
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
    launch = stage_tool_launch(args, tool)
    argv = [launch.binary, "--cc"]
    argv.extend(
        as_str_list(verilator_cfg.get("compile_args"), "build.verilator.compile_args")
        or ["--timing", "-sv", "--language", "1800-2023"]
    )
    if build.get("top_module"):
        argv.extend(["--top-module", str(build["top_module"])])
    argv.extend(expand_ocah_vendor_define_aliases(target_flags(compile_target, "verilator")))
    argv.extend(args.comp_arg or [])
    argv.extend(
        expand_ocah_vendor_define_aliases(
            [f"+define+{define}" for define in config_list(compile_target, "defines")]
            + [f"+define+{define}" for define in (args.define or [])]
        )
    )
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
        launch=launch,
    )


# cocotb is the single test framework across simulators, and every simulator goes through
# cocotb's Python runner (``cocotb_tools.runner``): one cocotb version, one launch path.
COCOTB_RUNNER_TOOLS = {"verilator", "xcelium", "vcs"}


def _cocotb_build_args(
    tool: str,
    flow: Flow,
    root: Path,
    build: dict[str, Any],
    run_target: dict[str, Any],
    compile_target: dict[str, Any],
    options: dict[str, Any],
    filelist: Path,
    args: argparse.Namespace,
) -> list[str]:
    defines = expand_ocah_vendor_define_aliases(
        [
            f"+define+{d}"
            for d in (config_list(run_target, "defines") or config_list(compile_target, "defines"))
        ]
        + [f"+define+{d}" for d in (args.define or [])]
    )
    if tool == "verilator":
        verilator_cfg = build_verilator_cfg(build)
        return [
            *(
                as_str_list(verilator_cfg.get("compile_args"), "build.verilator.compile_args")
                or ["--timing", "-sv", "--language", "1800-2023"]
            ),
            *expand_ocah_vendor_define_aliases(target_flags(run_target, "verilator")),
            *(args.comp_arg or []),
            *defines,
            *option_build_args(options, verilator_cfg, _build_jobs_arg(args)),
            "-f",
            str(filelist),
        ]
    if tool == "vcs":
        # cocotb's Vcs runner supplies -full64/-sverilog/-debug_access+all/+acc+3, loads its VPI
        # library and adds -top; it has no timescale argument, so the [build.vcs] timescale
        # (simulator default 1ns/1ps) is passed here, as the UVM flow does.
        vcs_cfg = build_vcs_cfg(build)
        timescale = str(vcs_cfg.get("timescale", "")).strip()
        return [
            *([f"-timescale={timescale}"] if timescale else []),
            *(target_flags(run_target, "vcs") or target_flags(compile_target, "vcs")),
            *(args.comp_arg or []),
            *defines,
            *vcs_build_args(options, vcs_cfg, _build_jobs_arg(args)),
            "-f",
            str(filelist),
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
    return _last_plusarg_wins(
        [
            *_render_list(as_str_list(run_mode.get("args"), "run_mode.args"), ctx),
            *_render_list(list(test.args or []), ctx),
        ]
    )


def _plusarg_key(arg: str) -> str | None:
    if arg.startswith("+") and "=" in arg:
        return arg.split("=", 1)[0]
    return None


def _last_plusarg_wins(rendered: list[str]) -> list[str]:
    """Return a new list where a later scalar `+key=value` wins.

    A testlist entry is more specific than the run mode it runs under, so when
    both set the same plusarg the entry is meant to override. `$value$plusargs`
    returns the *first* match, so leaving both on the command line hands the win
    to the run mode and the entry's value never reaches the design -- an
    override that reads as effective and is not. Whether that is visible depends
    on the simulator, because nothing reports the discarded one.

    Only scalar `+key=value` forms are collapsed. Bare flags, non-plusarg
    arguments, and every `+uvm_set_*` occurrence keep their relative order:
    UVM consumes each `+uvm_set_type_override=` / `+uvm_set_config_*` /
    `+uvm_set_verbosity=` / `+uvm_set_severity=` independently, so two
    type overrides share a key and collapsing them would drop one.

    Each drop is printed. Silently discarding an argument the config author
    wrote is the same class of problem as the one this function exists to fix:
    the command line stops matching the config and nothing says so.
    """
    final_at: dict[str, int] = {}
    for index, arg in enumerate(rendered):
        key = _plusarg_key(arg)
        if key is None or key.startswith("+uvm_set_"):
            continue
        final_at[key] = index
    kept: list[str] = []
    for index, arg in enumerate(rendered):
        key = _plusarg_key(arg)
        if key is not None and key in final_at and final_at[key] != index:
            print(
                f"PLUSARG: dropping {arg} -- overridden by {rendered[final_at[key]]}",
                flush=True,
            )
            continue
        kept.append(arg)
    return kept


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
    if (
        bool(getattr(args, "rebuild", False)) or bool(build_options.get("rebuild", False))
    ) and not args.dry_run:
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
        (stage_dir / "c_compile.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return rc


def _safe_build_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()) or "default"


def cocotb_python_paths(root: Path, cocotb_data: dict[str, Any]) -> list[Path]:
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
    # The coverage build is a sibling of the plain one, not a child of it.
    # Verilator's verilated.mk puts `..` on the make VPATH, so a coverage build
    # nested under the plain build dir resolves the cocotb main's `verilator.o`
    # to the plain build's copy, which was compiled without -DVM_COVERAGE. That
    # main never calls VerilatedCov::write, so the simulation finishes normally
    # and writes no coverage.dat.
    base_build = repo_path(root, build_dir) / (f"{tool}-coverage" if args.cov else tool)
    if tool == "vcs":
        base_build /= _safe_build_component(target_name)
    build_args = _cocotb_build_args(
        tool, flow, root, build, run_target, compile_target, options, filelist, args
    )

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
                "repo_root": str(root),
                "build_dir": str(base_build),
                "build_cov_dir": str(base_build / "cov_build.vdb"),
                "cov_dir": str(base_build / "coverage"),
            },
        )

    if wave_format and tool == "verilator":
        if wave_format not in {"fst", "vcd"}:
            raise ConfigError(f"Verilator cocotb waves support `fst` or `vcd`, got `{args.waves}`")
        trace_arg = "--trace-fst" if wave_format == "fst" else "--trace"
        if trace_arg not in build_args:
            build_args.append(trace_arg)

    if tool == "verilator":
        tool_ver = verilator_version(root)
    elif tool == "xcelium":
        tool_ver = xcelium_version(root)
    else:
        tool_ver = vcs_version(root)
    filelist_text = (
        filelist.read_text(encoding="utf-8", errors="replace")
        if filelist.is_file()
        else str(filelist)
    )
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
            *_filelist_sources_fingerprint(root, filelist),
            *_file_args_fingerprint(root, build_args),
            f"waves={wave_format}",
            f"cov={bool(args.cov)}",
        ],
    )
    sim_build = resolve_build_dir(base_build, options, fingerprint)
    build_record = sim_build / BUILD_RECORD_NAME
    rebuild, rebuild_reason = _build_record_decision(
        build_record,
        fingerprint,
        bool(args.rebuild) or bool(options.get("rebuild", False)),
    )
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
        "tool_version": tool_ver,
        "rebuild": rebuild,
        "rebuild_reason": rebuild_reason,
        "build_record": build_record,
    }


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
    if tool not in COCOTB_RUNNER_TOOLS:
        raise ConfigError(f"cocotb build supports tool verilator|xcelium|vcs, got `{tool}`")

    console = console_from_args(args)
    launch = stage_tool_launch(args, tool)
    reject_cocotb_launcher(launch)
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
    # `make -f Vtop.mk` separately. cocotb exposes no per-build jobs API, so
    # cocotb_make_jobs() maps the same config/CLI value onto that backend's make -j.
    _build_jobs = effective_build_jobs(options, _build_jobs_arg(args))
    if _build_jobs and _build_jobs > 1:
        env["MAKEFLAGS"] = f"-j{_build_jobs}"
        console.artifact("cocotb_make_jobs", str(_build_jobs))
    env = launch_env(launch, env)
    # Verilator-only: scope cocotb's global --public-flat-rw to the tb top (see
    # cocotb_public_scope). Empty/absent config -> cocotb's default behaviour is kept.
    public_scope_vlt = ""
    if tool == "verilator":
        _scope_rel = str(build_verilator_cfg(build).get("public_scope") or "").strip()
        if _scope_rel:
            public_scope_vlt = str(repo_path(root, _scope_rel))
            console.artifact("public_scope", public_scope_vlt)
    rebuild_note = f"rebuild={info['rebuild']}"
    if info["rebuild_reason"]:
        rebuild_note += f" reason={info['rebuild_reason']}"
    console.artifact("build", f"{info['sim_build']} ({rebuild_note})")
    write_script(
        script_path,
        root,
        [sys.executable, "-c", "from cocotb_tools.runner import get_runner"],
        args.dry_run,
    )
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
                with (
                    scoped_environ(env),
                    cocotb_make_jobs(_build_jobs),
                    cocotb_public_scope(public_scope_vlt),
                    cocotb_tool_binary(tool, launch.binary),
                ):
                    runner.build(
                        sources=[],
                        hdl_toplevel=info["top_module"],
                        build_dir=info["sim_build"],
                        build_args=info["build_args"],
                        includes=[
                            repo_path(root, value)
                            for value in as_str_list(build.get("incdirs"), "build.incdirs")
                        ],
                        waves=bool(_wave_format(args, tool)),
                        always=info["rebuild"],
                    )
    _write_build_record(info["build_record"], info["fingerprint"], info["tool_version"], False)
    _mark_cocotb_prebuilt(args, target_name)
    return 0


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
    args ONLY if the hook's ``stage`` accepts them, so a hook that takes only
    ``(item, seed, cwd)`` also works. SEP uses ``sim_args`` to honor
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
    test_args: list[str] | None = None,
) -> int:
    if tool not in COCOTB_RUNNER_TOOLS:
        raise ConfigError(f"cocotb sim supports tool verilator|xcelium|vcs, got `{tool}`")

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
    test_args = (
        list(test_args)
        if test_args is not None
        else _sim_test_args(sim_cfg, run_mode, test, args, seed, root)
    )

    # Coverage: same cocotb test, simulator-native collection. Verilator does line/toggle only;
    # Xcelium collects full SV coverage. Both controlled by --cov and overridable via [coverage].
    if args.cov:
        tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
        coverage_ctx = {
            "cov_dir": str(cov_dir),
            "build_dir": str(sim_build),
            "build_cov_dir": str(sim_build / "cov_build.vdb"),
            "repo_root": str(root),
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
        elif tool == "vcs":
            ucli_path = item_dir / "scripts" / f"waves.{item}.ucli"
            _vcs_wave_ucli(
                ucli_path=ucli_path,
                waves_dir=waves_dir,
                item=item,
                top=top_module,
                wave_format=wave_format,
                range_info=_wave_range(args),
                dry_run=args.dry_run,
            )
            test_args += ["-ucli", "-i", str(ucli_path)]

    launch = stage_tool_launch(args, tool)
    reject_cocotb_launcher(launch)
    python_paths = cocotb_python_paths(root, cocotb_data)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths if str(path))
    env["RANDOM_SEED"] = str(seed)
    # The directory the model was elaborated into. A coverage run builds under
    # <tool>/coverage, so a test that records which model it simulated must
    # read this rather than assume the plain <tool> path.
    env["OCAH_SIM_BUILD_DIR"] = str(sim_build)
    env = apply_option_env(
        options,
        env,
        build_verilator_cfg(build) if tool == "verilator" else None,
    )
    if tool == "vcs" and wave_format:
        env = _vcs_wave_env(env, wave_format, bool(args.dry_run))
    env = launch_env(launch, env)
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
        # Behavioral responders that $readmemh/$fopen flat image names read them from the
        # sim CWD at time 0, and the cocotb runner runs each test from its per-test run
        # dir, so the source test-dir images are copied there. Per-test boot_firmware
        # staging overwrites the TCM images it owns.
        src_test_dir = repo_path(root, str(cocotb_data.get("test_dir", "")))
        if src_test_dir.is_dir():
            for pattern in ("*.hex", "*.parhex"):
                for asset in src_test_dir.glob(pattern):
                    shutil.copy2(asset, item_dir / asset.name)
        # cocotb runner chdir's to item_dir, so a time-0 image hook writes there.
        _run_sim_prestage(
            root,
            cocotb_data,
            item,
            seed,
            item_dir,
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
        "build_record": str(info["build_record"]),
        "fingerprint": str(info["fingerprint"]),
        "tool_version": str(info["tool_version"]),
        "python_paths": [str(path) for path in python_paths if str(path)],
        "public_scope_vlt": public_scope_vlt,
        "binary": launch.binary,
        "default_binary": COCOTB_DEFAULT_BINARY.get(tool, tool),
        "runner_class": COCOTB_RUNNER_CLASS.get(tool, ""),
    }
    runner_body = f"""#!/usr/bin/env python3
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

payload = {payload!r}

for path in payload["python_paths"]:
    if path and path not in sys.path:
        sys.path.insert(0, path)

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
    for module_name in ("cocotb_tools.runner",):
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
    for module_name in ("cocotb_tools.runner",):
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

@contextmanager
def scoped_tool_binary(tool, runner_class, default, binary):
    if not runner_class or binary == default:
        yield
        return
    import importlib
    import shutil
    module = importlib.import_module("cocotb_tools.runner")
    cls = getattr(module, runner_class)

    def probe(self):
        found = shutil.which(binary)
        if found is None:
            raise SystemExit(f"ERROR: {{binary}} executable not found!")
        self.executable = found

    def rename(commands):
        renamed = []
        for cmd in commands:
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == default:
                renamed.append([binary, *cmd[1:]])
            else:
                renamed.append(cmd)
        return renamed

    def make_wrapper(orig):
        def wrapper(self):
            return rename(orig(self))
        return wrapper

    saved = {{}}
    if tool == "verilator":
        saved["_simulator_in_path_build_only"] = cls._simulator_in_path_build_only
        cls._simulator_in_path_build_only = probe
    else:
        saved["_simulator_in_path"] = cls._simulator_in_path
        cls._simulator_in_path = probe
        for name in ("_build_command", "_test_command"):
            saved[name] = getattr(cls, name)
            setattr(cls, name, make_wrapper(saved[name]))
    try:
        yield
    finally:
        for name, original in saved.items():
            setattr(cls, name, original)

print(f"# cocotb {{payload['tool']}} runner", flush=True)
runner = get_runner(payload["tool"])
with scoped_public_scope(payload["public_scope_vlt"]), scoped_verilator_wave_format(payload["tool"], payload["wave_format"]), scoped_tool_binary(payload["tool"], payload["runner_class"], payload["default_binary"], payload["binary"]):
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
        with open(payload["build_record"], "w", encoding="utf-8") as record:
            json.dump(
                {{
                    "fingerprint": payload["fingerprint"],
                    "tool_version": payload["tool_version"],
                    "written_at": datetime.now(timezone.utc).isoformat(),
                }},
                record,
                indent=2,
            )
            record.write("\\n")
    else:
        print(f"# cocotb {{payload['tool']}} build skipped: pre-built during elaborate", flush=True)
        # `runner.build()` is what normally populates the runner's source
        # lists, and Xcelium's `_test_command` concatenates all three to decide
        # whether any VHDL source needs `-vhpi`. On the pre-built path build()
        # never runs, so those attributes are absent and `test()` raises with an
        # AttributeError before the simulator is ever launched. Only the missing
        # ones are filled, so a cocotb version that does set them keeps its own
        # values. Empty is the correct value here: this flow compiles from a
        # file list rather than from runner sources, and has no VHDL.
        for _src_attr in ("_sources", "_vhdl_sources", "_verilog_sources"):
            if not hasattr(runner, _src_attr):
                setattr(runner, _src_attr, [])

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
    return expand_ocah_vendor_define_aliases(
        [f"+define+{d}" for d in config_list(compile_target, "defines")]
        + [f"+define+{d}" for d in (args.define or [])]
    )


# VCS's bare "-ntb_opts uvm" resolves to uvm-1.1, whose global
# uvm_report_error lacks the context_name/report_enabled_checked parameters
# that the vendored OpenTitan prim_assert macros pass; default to the 1.2
# library. [build.vcs].uvm_lib overrides the selection (uvm-1.2 is the floor
# the vendored OpenTitan asserts compile against).
_VCS_UVM_LIB = "uvm-1.2"


def _vcs_uvm_lib(vcs_cfg: dict[str, Any]) -> str:
    lib = str(vcs_cfg.get("uvm_lib", "")).strip()
    return lib or _VCS_UVM_LIB


def _uvm_testname_override(extra_args: list[str]) -> str:
    """Return the +UVM_TESTNAME= value supplied in extra_args, or '' when absent.

    UVM takes the FIRST +UVM_TESTNAME occurrence, and the simulator-shipped
    uvm-1.2 library applies command-line factory overrides only after
    run_test() has created the test component, so +uvm_set_type_override
    cannot swap the test itself. Selecting a factory-registered subclass of a
    testlist scenario therefore comes through +UVM_TESTNAME: when the caller
    supplies one, the runner must not emit its testlist-mapped name ahead of
    it.
    """
    for arg in extra_args:
        if arg.startswith("+UVM_TESTNAME="):
            return arg[len("+UVM_TESTNAME=") :]
    return ""


def _vcs_uvm_precompile_cmd(
    vcs_cfg: dict[str, Any], compile_target: dict[str, Any], args: argparse.Namespace
) -> str:
    """The UVM-library precompile line for the split vlogan -> vcs flow.

    Carries the same defines as the user-source analysis: size-changing defines
    (e.g. UVM_PACKER_MAX_BYTES) must agree across every analysis step of one
    work library, or consumers of the precompiled uvm_pkg see a mismatched
    packer geometry. Tokens are shell-quoted because the line is embedded in a
    `bash -c` script (define values may carry quotes).
    """
    return " ".join(
        [
            "vlogan",
            "-full64",
            "-ntb_opts",
            shlex.quote(_vcs_uvm_lib(vcs_cfg)),
            *(shlex.quote(d) for d in _vcs_defines(compile_target, args)),
        ]
    )


def _vcs_preamble(vcs_cfg: dict[str, Any], framework: str) -> list[str]:
    pre: list[str] = []
    if bool(vcs_cfg.get("sverilog", True)):
        pre.append("-sverilog")
    pre.append("-full64")
    if bool(vcs_cfg.get("uvm", framework == "uvm")):
        pre += ["-ntb_opts", _vcs_uvm_lib(vcs_cfg)]
    timescale = str(vcs_cfg.get("timescale", "")).strip()
    if timescale:
        pre.append(f"-timescale={timescale}")
    return pre


def _vcs_uum_elab_args(
    vcs_cfg: dict[str, Any],
    framework: str,
    options: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    """Return UUM elaboration options after vlogan has already parsed all sources."""
    elab = ["-full64"]
    if bool(vcs_cfg.get("uvm", framework == "uvm")):
        elab += ["-ntb_opts", _vcs_uvm_lib(vcs_cfg)]
    elab += vcs_build_args(options, vcs_cfg, _build_jobs_arg(args))
    if _wave_format(args, "vcs"):
        elab.append("-debug_access+all")
    return elab


def _vcs_resolve_build(
    flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
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
    # Uniform build-tree convention `build/<framework>/<tool>/`: the configured work_dir carries
    # the framework segment (e.g. build/uvm), the runner appends the tool — mirroring how the
    # cocotb build appends its tool subdir. Generated filelists stay directly under work_dir.
    base_build = repo_path(root, required_path(build, "work_dir", "build", str(flow.path))) / "vcs"
    if args.cov:
        base_build /= "coverage"

    elab_args = [
        *_vcs_preamble(vcs_cfg, flow.framework),
        *_vcs_defines(compile_target, args),
        *target_flags(compile_target, "vcs"),
        *vcs_build_args(options, vcs_cfg, _build_jobs_arg(args)),
    ]
    wave_format = _wave_format(args, "vcs")
    if wave_format:
        elab_args.append("-debug_access+all")

    # `-cm ...` instrumentation from [coverage.vcs] (simulators.toml
    # coverage_defaults merge). The raw args feed the fingerprint; the
    # rendered paths anchor at the resolved build dir, so they are appended
    # after fingerprinting (both elaboration shapes consume `elab_args`).
    coverage_compile_args: list[str] = []
    if args.cov:
        tool_cov = coverage_cfg(sim_cfg).get("vcs", {})
        if not isinstance(tool_cov, dict):
            raise ConfigError("coverage.vcs must be a table")
        coverage_compile_args = as_str_list(
            tool_cov.get("compile_args"), "coverage.vcs.compile_args"
        )

    filelist_text = (
        filelist.read_text(encoding="utf-8", errors="replace")
        if filelist.is_file()
        else str(filelist)
    )
    fingerprint = build_fingerprint(
        build_args=elab_args,
        top_module=top,
        tool_version=vcs_version(root),
        filelist_text=filelist_text,
        extra=[
            *cache_key_extra(options),
            *_target_fingerprint_extra(target_name, compile_target),
            *_bender_sources_fingerprint(root, build),
            f"waves={wave_format}",
            f"cov={bool(args.cov)}",
            *coverage_compile_args,
        ],
    )
    build_dir = resolve_build_dir(base_build, options, fingerprint)
    coverage_args = _render_list(
        coverage_compile_args,
        {
            "tool": "vcs",
            "target": target_name,
            "repo_root": str(root),
            "build_dir": str(build_dir),
            "build_cov_dir": str(build_dir / "cov_build.vdb"),
            "cov_dir": str(build_dir / "coverage"),
        },
    )
    elab_args += coverage_args
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
        "coverage_args": coverage_args,
    }


def vcs_analyze(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
    """Three-step `compile` stage: analyze sources into the work library with vlogan."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    vcs_cfg = info["vcs_cfg"]
    launch = stage_tool_launch(args, "vcs")
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
            f'set -euo pipefail\n{_vcs_uvm_precompile_cmd(vcs_cfg, info["compile_target"], args)}\nexec "$@"',
            "vcs-analyze",
            *analyze_argv,
        ]
    else:
        argv = analyze_argv
    console_from_args(args).artifact("build", info["build_dir"])
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=info["build_dir"],
        verbose=args.verbose,
        timeout_sec=args.timeout,
        launch=launch,
    )


def vcs_build(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    *,
    include_filelist: bool,
) -> int:
    """Elaborate to a `simv`. `include_filelist=True` is the two-step combined build (vcs -f ...);
    `False` is the three-step elaborate that consumes the already-analyzed library."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    build_dir = info["build_dir"]
    vcs_cfg = info["vcs_cfg"]
    launch = stage_tool_launch(args, "vcs")
    if include_filelist:
        argv = [launch.binary, *info["elab_args"]]
        argv += ["-f", str(info["filelist"])]
    else:
        # UUM consumes the work library produced by vlogan. Source-language,
        # timescale, defines, and target flags are parse-only options and VCS
        # rejects them when no source file is present.
        argv = [
            launch.binary,
            *_vcs_uum_elab_args(
                vcs_cfg,
                flow.framework,
                build_options_cfg(info["build"]),
                args,
            ),
            *info["coverage_args"],
        ]
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
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=build_dir,
        verbose=args.verbose,
        timeout_sec=args.timeout,
        launch=launch,
    )


def vcs_sim(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str,
    args: argparse.Namespace,
    item_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    seed: int,
    test_args: list[str] | None = None,
) -> int:
    """Run a built simv for one test/seed. The simv is reused across all seeds."""
    info = _vcs_resolve_build(flow, root, sim_cfg, args)
    simv = info["simv"]
    vcs_cfg = info["vcs_cfg"]
    test = catalog.tests[item]
    run_mode = selected_run_mode(sim_cfg, test, args)
    results_dir = item_dir / "results"
    waves_dir = item_dir / "waves"
    uvm_test = test.module or test.name

    extra_args = (
        list(test_args)
        if test_args is not None
        else _sim_test_args(sim_cfg, run_mode, test, args, seed, root)
    )
    argv = [str(simv)]
    if bool(vcs_cfg.get("uvm", flow.framework == "uvm")) and not _uvm_testname_override(extra_args):
        argv.append(f"+UVM_TESTNAME={uvm_test}")
    argv.append(f"+ntb_random_seed={seed}")
    argv += extra_args
    if args.cov:
        tool_cov = coverage_cfg(sim_cfg).get("vcs", {})
        if not isinstance(tool_cov, dict):
            raise ConfigError("coverage.vcs must be a table")
        cov_dir = item_dir / "coverage"
        argv += _render_list(
            as_str_list(tool_cov.get("sim_args"), "coverage.vcs.sim_args"),
            {
                "tool": "vcs",
                "target": info["target_name"],
                "build_dir": str(info["build_dir"]),
                "build_cov_dir": str(info["build_dir"] / "cov_build.vdb"),
                "cov_dir": str(cov_dir),
                "run_dir": str(item_dir),
                "item": item,
                "seed": str(seed),
            },
        )
        if not args.dry_run:
            cov_dir.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] | None = None
    wave_format = _wave_format(args, "vcs")
    if wave_format:
        if not args.dry_run:
            waves_dir.mkdir(parents=True, exist_ok=True)
        ucli_path = item_dir / "scripts" / f"waves.{item}.ucli"
        _vcs_wave_ucli(
            ucli_path=ucli_path,
            waves_dir=waves_dir,
            item=item,
            top=info["top"],
            wave_format=wave_format,
            range_info=_wave_range(args),
            dry_run=args.dry_run,
        )
        argv += ["-ucli", "-i", str(ucli_path)]
        env = _vcs_wave_env(dict(os.environ), wave_format, bool(args.dry_run))
    console = console_from_args(args)
    console.artifact("simv", simv)
    console.artifact("test", f"{uvm_test} seed={seed}")
    if not args.dry_run:
        results_dir.mkdir(parents=True, exist_ok=True)
    timeout_sec = resolve_timeout_sec(sim_cfg, test, run_mode, args)
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=item_dir,
        env=env,
        verbose=args.verbose,
        timeout_sec=timeout_sec,
        launch=stage_tool_launch(args, "vcs"),
    )


# --- Xcelium (Cadence) stages -------------------------------------------------------------------
# Three-step flow: xmvlog (analyze) -> xmelab (elaborate -> snapshot) -> xmsim (simulate). The
# elaborated snapshot is the reusable build artifact (the analogue of VCS simv): every seed in a
# regression runs the same snapshot via `xmsim -svseed <seed>`. The combined two-step build is
# `xrun -elaborate` (analyze+elaborate -> snapshot, no run).


def _xcelium_defines(compile_target: dict[str, Any], args: argparse.Namespace) -> list[str]:
    return expand_ocah_vendor_define_aliases(
        [f"+define+{d}" for d in config_list(compile_target, "defines")]
        + [f"+define+{d}" for d in (args.define or [])]
    )


def _xcelium_common(xcelium_cfg: dict[str, Any], framework: str) -> list[str]:
    common: list[str] = []
    if bool(xcelium_cfg.get("uvm", framework == "uvm")):
        common.append("-uvm")
    timescale = str(xcelium_cfg.get("timescale", "")).strip()
    if timescale:
        common += ["-timescale", timescale]
    return common


def _xcelium_resolve_build(
    flow: Flow, root: Path, sim_cfg: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
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
    # Same `build/<framework>/<tool>/` convention as the VCS resolver above.
    base_build = (
        repo_path(root, required_path(build, "work_dir", "build", str(flow.path))) / "xcelium"
    )
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

    filelist_text = (
        filelist.read_text(encoding="utf-8", errors="replace")
        if filelist.is_file()
        else str(filelist)
    )
    fingerprint = build_fingerprint(
        build_args=[*elab_args, *_xcelium_defines(compile_target, args)],
        top_module=top,
        tool_version=xcelium_version(root),
        filelist_text=filelist_text,
        extra=[
            *cache_key_extra(options),
            *_target_fingerprint_extra(target_name, compile_target),
            *_bender_sources_fingerprint(root, build),
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


def xcelium_analyze(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
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
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=info["build_dir"],
        verbose=args.verbose,
        timeout_sec=args.timeout,
        launch=stage_tool_launch(args, "xcelium"),
    )


def xcelium_build(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    *,
    include_filelist: bool,
) -> int:
    """Elaborate to a snapshot. `include_filelist=True` is the two-step combined build
    (`xrun -elaborate -f <filelist>`); `False` is the three-step `xmelab` after analysis."""
    info = _xcelium_resolve_build(flow, root, sim_cfg, args)
    build_dir = info["build_dir"]
    launch = stage_tool_launch(args, "xcelium")
    if include_filelist:
        argv = [
            launch.binary,
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
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=build_dir,
        verbose=args.verbose,
        timeout_sec=args.timeout,
        launch=launch,
    )


def xcelium_sim(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str,
    args: argparse.Namespace,
    item_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    seed: int,
    test_args: list[str] | None = None,
) -> int:
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
    argv += (
        list(test_args)
        if test_args is not None
        else _sim_test_args(sim_cfg, run_mode, test, args, seed, root)
    )
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
    return run_subprocess(
        argv,
        root,
        log_path,
        args.dry_run,
        script_path,
        env_path,
        args.quiet,
        cwd=item_dir,
        verbose=args.verbose,
        timeout_sec=timeout_sec,
        launch=stage_tool_launch(args, "xcelium"),
    )


# --- Coverage merge/report ----------------------------------------------------------------------
# Simulation owns native database collection. These stages select the final leaf artifacts, merge
# only compatible databases, and normalize vendor reports under `<run_dir>/cov/`.


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
    # The design database lands where the elaboration's `-cm_dir` pointed:
    # the UVM framework builds through the native VCS resolver, cocotb
    # through the cocotb build info.
    if flow.framework == "uvm":
        build_dir = Path(_vcs_resolve_build(flow, root, sim_cfg, args)["build_dir"])
    else:
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
        raise ConfigError(f"coverage.{key} references missing file(s): {', '.join(missing)}")
    return paths


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_coverage_policy(
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
) -> list[str]:
    if not exclusions:
        return []
    if tool == "vcs" and phase == "report":
        argv: list[str] = []
        for path in exclusions:
            argv.extend(["-elfile", path])
        return argv
    raise ConfigError(
        f"{tool} coverage auxiliary files require coverage_policy.toml native_files "
        "with explicit backend arguments"
    )


def coverage_stage(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    tool: str,
    run_dir: Path,
    phase: str,
    args: argparse.Namespace,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    quiet: bool,
) -> int:
    cov = coverage_cfg(sim_cfg)
    tool_cov = cov.get(tool, {}) if isinstance(cov.get(tool, {}), dict) else {}
    if not tool_cov:
        raise ConfigError(f"no coverage configuration is available for tool `{tool}`")

    paths = coverage_run_paths(run_dir, coverage_merged_name(tool, tool_cov))
    cov_dir = paths.cov_dir
    merged = paths.merged
    report_dir = paths.report_dir
    manifest_path = paths.manifest
    parser = coverage_parser_name(tool_cov)
    backend = coverage_backend(tool, tool_cov)
    supported_metrics = _coverage_supported_metrics(args, tool)
    exclusions = _coverage_auxiliary_files(flow, root, tool_cov, "exclude_files")
    policy = resolve_coverage_policy(flow, root, tool, tool_cov)
    design_db = _coverage_design_db(flow, root, sim_cfg, tool_cov, args)
    ctx = {
        "run_dir": str(run_dir),
        "cov_dir": str(cov_dir),
        "merged": str(merged),
        "report": str(report_dir),
        "tool": tool,
        "design_db": str(design_db or ""),
    }

    # `--cov-combine` hands the merge phase finished runs instead of this run's leaves.
    run_plan = getattr(args, "_cov_combine_plan", None) if phase == "merge" else None
    if phase == "merge":
        key = "combine_cmd" if run_plan is not None else "merge_cmd"
    else:
        key = "report_cmd"
    template = as_str_list(tool_cov.get(key), f"coverage.{tool}.{key}")
    if not template:
        raise ConfigError(f"coverage.{tool}.{key} must not be empty")
    launch = stage_tool_launch(args, tool)

    if args.dry_run:
        if run_plan is not None:
            dry_inputs = run_plan.input_paths()
        else:
            dry_inputs = [str(run_dir / "<coverage-input>")] if phase == "merge" else []
        policy_args = [
            *native_policy_args(policy, tool=tool, phase=phase),
            *_legacy_coverage_policy_args(
                tool=tool,
                phase=phase,
                exclusions=exclusions,
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
            launch=launch,
        )

    cov_dir.mkdir(parents=True, exist_ok=True)
    if phase == "merge":
        if run_plan is not None:
            discovery = run_plan.discovery(root)
        else:
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
        if run_plan is None and "{design_db}" in " ".join(template):
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
                {"path": repo_rel(root, path), "sha256": _file_sha256(path)} for path in exclusions
            ],
            "legacy_waivers": [],
        }
        if run_plan is not None:
            manifest["target"] = run_plan.target
            manifest["build_fingerprint"] = run_plan.build_fingerprint
            manifest["combine"] = run_plan.manifest_payload(root)
            input_paths = run_plan.input_paths()
        else:
            if design_db is not None:
                manifest["artifacts"]["design_db"] = repo_rel(root, design_db)
            input_paths = [str(repo_path(root, entry.path)) for entry in discovery.inputs]
        write_json(manifest_path, manifest)
        argv = [
            *render_tokens(template, ctx, input_paths),
            *native_policy_args(policy, tool=tool, phase="merge"),
            *_legacy_coverage_policy_args(
                tool=tool,
                phase="merge",
                exclusions=exclusions,
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
            launch=launch,
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
        raise CoverageError("coverage manifest DUT/tool does not match the requested report stage")
    if not artifact_ready(merged):
        raise CoverageError(f"merged coverage database is missing or empty: {merged}")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_policy_args = [
        *native_policy_args(policy, tool=tool, phase="report"),
        *_legacy_coverage_policy_args(
            tool=tool,
            phase="report",
            exclusions=exclusions,
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
        launch=launch,
    )
    if rc != 0:
        manifest["status"] = "ERROR"
        manifest["report_return_code"] = rc
        write_json(manifest_path, manifest)
        return rc

    # The tool applies its exclusion inputs while it reports, so the report above carries the
    # effective figures only. A second report without those inputs supplies the raw figures;
    # without exclusion inputs the one report is both, and a raw report left by an earlier
    # grading would misstate this one.
    raw_report_dir = paths.raw_report_dir
    if report_policy_args:
        raw_report_dir.mkdir(parents=True, exist_ok=True)
        rc = run_subprocess(
            render_tokens(template, {**ctx, "report": str(raw_report_dir)}),
            root,
            log_path.with_name(f"{log_path.stem}.raw{log_path.suffix}"),
            False,
            script_path.with_name(f"{script_path.stem}.raw{script_path.suffix}"),
            env_path.with_name(f"{env_path.stem}.raw{env_path.suffix}"),
            quiet,
            cwd=cov_dir,
            verbose=args.verbose,
            timeout_sec=args.timeout,
            launch=launch,
        )
        if rc != 0:
            manifest["status"] = "ERROR"
            manifest["report_return_code"] = rc
            write_json(manifest_path, manifest)
            return rc
    elif raw_report_dir.exists():
        shutil.rmtree(raw_report_dir)

    threshold = args.fail_under
    if threshold is None:
        threshold = coverage_fail_under(tool, tool_cov)
    threshold = threshold if threshold is not None else 0.0
    parsed = parse_coverage_run(
        parser=parser,
        dut=flow.name,
        tool=tool,
        manifest=manifest,
        merged=merged,
        report_dir=report_dir,
        log_path=log_path,
        raw_report_dir=raw_report_dir if report_policy_args else None,
    )
    write_json(paths.raw_details, parsed.details.to_dict())
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
        tool_version=_coverage_tool_version(tool, root),
        supported_metrics=supported_metrics,
    )
    _report_metric_families(parsed.details.metrics, log_path, console_from_args(args))
    if not grade.threshold_met:
        with log_path.open("a", encoding="utf-8") as log:
            if not grade.compatibility_threshold_met:
                log.write(f"# COVERAGE THRESHOLD: {grade.total_percent} < {grade.threshold}\n")
            for outcome in grade.thresholds:
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


def _report_metric_families(metrics: list[Any], log_path: Path, console: Console) -> None:
    """One `raw=` / `effective=` pair per metric family, in the stage log and on the console."""
    pairs = []
    for record in metrics:
        raw = "-" if record.raw_percent is None else f"{record.raw_percent:.2f}"
        effective = "-" if record.effective_percent is None else f"{record.effective_percent:.2f}"
        pairs.append((record.metric_family, raw, effective))
    if not pairs:
        return
    with log_path.open("a", encoding="utf-8") as log:
        for family, raw, effective in pairs:
            log.write(f"# COVERAGE FAMILY: {family} raw={raw} effective={effective}\n")
    console.event(
        "coverage",
        " ".join(f"{family}={raw}/{effective}" for family, raw, effective in pairs)
        + " (raw/effective)",
    )


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


@dataclass(frozen=True)
class FormalApp:
    """The app a formal item resolves to: its name, the backend tool that runs it, the
    `[formal.apps.<app>.<tool>]` table, and the launch directory."""

    name: str
    tool: str
    table: dict[str, Any]
    cwd: Path


def resolve_formal_app(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str,
    args: argparse.Namespace,
    tool: str,
) -> FormalApp:
    """Resolve the formal item's app table for `tool`, falling back to the app's `default_tool`
    when the selected tool has no table."""
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
    cwd = _repo_or_dut_path(root, flow, str(tool_cfg.get("cwd", ".")))
    return FormalApp(name=app_name, tool=tool, table=tool_cfg, cwd=cwd)


def formal_run_stage(
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    item: str | None,
    args: argparse.Namespace,
    tool: str,
    simulators: dict[str, Any],
    ctx: dict[str, str],
    log_path: Path,
    script_path: Path,
    env_path: Path,
) -> int:
    """Launch one formal app through the tool's `argv` template.

    The template comes from the app table's `argv` when set, else from the tool's registry entry.
    `--proof-depth` and `--formal-arg` reach the command line only through their placeholders,
    so a template without the placeholder rejects the option instead of dropping it.
    """
    if item is None:
        raise ConfigError("formal_run stage requires a formal task item")
    app = resolve_formal_app(flow, root, sim_cfg, catalog, item, args, tool)
    tool, tool_cfg, cwd = app.tool, app.table, app.cwd
    sim_tool = simulators.get(tool, {})
    if not isinstance(sim_tool, dict):
        sim_tool = {}
    launch = tool_launch(simulators, tool)
    binary = launch.binary
    script = str(tool_cfg.get("script", "")).strip()
    where = f"{flow.path} [formal.apps.{app.name}.{tool}]"
    if "argv" in tool_cfg:
        template = validate_formal_argv_template(tool_cfg["argv"], f"{where}.argv")
    elif "argv" in sim_tool:
        template = validate_formal_argv_template(sim_tool["argv"], f"simulators.toml [{tool}].argv")
    else:
        raise ConfigError(
            f"{where}: no launch template; simulators.toml [{tool}] carries no `argv` "
            "and the app table sets none"
        )
    used = formal_template_placeholders(template)
    if "script" in used and not script:
        raise ConfigError(
            f"{where}: the launch template uses {{script}} but the app table sets no `script`"
        )
    proof_depth = None if args.proof_depth is None else str(args.proof_depth)
    if proof_depth is not None and "proof_depth" not in used:
        raise ConfigError(
            f"--proof-depth is not routed: the `{tool}` launch template for formal app "
            f"`{app.name}` has no {{proof_depth}} placeholder"
        )
    formal_args = list(args.formal_arg or [])
    if formal_args and "formal_args" not in used:
        raise ConfigError(
            f"--formal-arg is not routed: the `{tool}` launch template for formal app "
            f"`{app.name}` has no {{formal_args}} placeholder"
        )
    argv = render_formal_argv(
        template,
        scalars={
            "binary": binary,
            "script": script,
            "cwd": str(cwd),
            "run_dir": ctx.get("run_dir", ""),
            "item": item,
        },
        lists={
            "args": as_str_list(tool_cfg.get("args"), f"formal.apps.{app.name}.{tool}.args"),
            "formal_args": formal_args,
        },
        optional={"proof_depth": proof_depth},
    )
    console_from_args(args).artifact("formal_app", f"{app.name} ({tool})")
    return run_subprocess(
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
        launch=launch,
    )


def _resolve_stage_kind(kind: str, framework: str, tool: str, where: Any) -> str:
    """Map a generic stage kind to its concrete (tool, framework) adapter.

    Generic kinds keep the profile stage graph framework-neutral; the concrete adapter is
    picked here at dispatch time. `vcs_uvm_build` is internal-only (the folded analyze +
    elaborate two-step for SV-UVM on VCS) and never appears in configs.
    """
    if kind == "filelist":
        return "bender_filelist"
    if kind == "hdl_compile":
        if framework == "uvm":
            if tool == "vcs":
                return "vcs_uvm_build"
            raise ConfigError(
                f"{where}: framework `uvm` has no `hdl_compile` adapter for tool `{tool}` yet"
            )
        return "cocotb_build"
    if kind == "sim":
        if framework == "uvm":
            if tool == "vcs":
                return "vcs_sim"
            raise ConfigError(
                f"{where}: framework `uvm` has no `sim` adapter for tool `{tool}` yet"
            )
        return "cocotb_sim"
    return kind


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
    kind = _resolve_stage_kind(str(stage.get("kind", "")), flow.framework, tool, flow.path)
    seed = (
        seed_override
        if seed_override is not None
        else (
            seed_for_item(catalog, sim_cfg, args, item) if item else as_int(args.seed, "seed") or 1
        )
    )
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
        "executor": str(getattr(args, "executor", None) or "local"),
        "target": target_name,
        "item": item or "",
        "seed": str(seed),
        # `jobs` is an alias of `sim_jobs` in stage templates.
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
    formal_report: dict[str, Any] | None = None
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
            rc = coverage_stage(
                flow,
                root,
                sim_cfg,
                tool,
                run_dir,
                "merge",
                args,
                log_path,
                script_path,
                env_path,
                args.quiet,
            )
        elif kind == "coverage_report":
            rc = coverage_stage(
                flow,
                root,
                sim_cfg,
                tool,
                run_dir,
                "report",
                args,
                log_path,
                script_path,
                env_path,
                args.quiet,
            )
        elif kind == "clean":
            rc = clean_stage(stage, root, ctx, args.dry_run)
        elif kind == "c_compile":
            rc = c_compile_stage(
                flow,
                root,
                sim_cfg,
                catalog,
                item,
                args,
                tool,
                stage_dir,
                log_path,
                script_path,
                env_path,
                seed,
            )
        elif kind == "formal_run":
            rc = formal_run_stage(
                flow,
                root,
                sim_cfg,
                catalog,
                item,
                args,
                tool,
                simulators,
                ctx,
                log_path,
                script_path,
                env_path,
            )
        elif kind in {"bender_filelist", "verilator_filelist"}:
            # The cocotb framework maps the logical `flist` stage to `bender_filelist` for every
            # tool, so the tool-dependent stub ordering keys off the actual target tool here.
            rc = generate_filelist(
                flow,
                root,
                sim_cfg,
                args.dry_run,
                log_path,
                script_path,
                env_path,
                args.quiet,
                verbose=args.verbose,
                tool=tool,
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
                rc = generate_filelist(
                    flow,
                    root,
                    sim_cfg,
                    args.dry_run,
                    log_path,
                    script_path,
                    env_path,
                    args.quiet,
                    verbose=args.verbose,
                )
                if rc == 0:
                    rc = verilator_compile(
                        flow, root, sim_cfg, stage_name, tool, args, log_path, script_path, env_path
                    )
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
            sim_args = _sim_test_args(
                sim_cfg,
                selected_run_mode(sim_cfg, catalog.tests[item], args),
                catalog.tests[item],
                args,
                seed,
                root,
            )
            rc = cocotb_sim(
                flow,
                root,
                sim_cfg,
                catalog,
                item,
                args,
                tool,
                stage_dir,
                log_path,
                script_path,
                env_path,
                seed,
                test_args=sim_args,
            )
            # Mirror the documented metadata shape enough for cache/debug consumers. Detailed cache
            # decisions are made inside `cocotb_sim`; this records the invariant stage-level inputs.
            metadata["build_cache"] = {
                "enabled": bool(
                    build_cfg(flow, sim_cfg).get("options", {}).get("cache_enabled", False)
                ),
                "rebuild": bool(args.rebuild),
            }
            sim_info = _cocotb_build_info(flow, root, sim_cfg, args, tool)
            metadata["target_build"] = _cocotb_target_build_metadata(sim_info, tool)
            _stamp_provenance(
                root,
                log_path,
                metadata,
                fingerprint=str(sim_info.get("fingerprint", "")) or None,
                filelist=sim_info.get("filelist"),
                dry_run=bool(args.dry_run),
                sim_args=sim_args,
                cwd=stage_dir,
            )
        elif kind == "vcs_filelist":
            rc = generate_filelist(
                flow,
                root,
                sim_cfg,
                args.dry_run,
                log_path,
                script_path,
                env_path,
                args.quiet,
                verbose=args.verbose,
                tool="vcs",
            )
        elif kind == "vcs_analyze":
            rc = vcs_analyze(flow, root, sim_cfg, args, log_path, script_path, env_path)
        elif kind == "vcs_compile":
            rc = vcs_build(
                flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=True
            )
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "vcs_elaborate":
            rc = vcs_build(
                flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=False
            )
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "vcs_uvm_build":
            # Canonical two-step build for SV-UVM on VCS: analyze (vlogan + simulator-owned UVM
            # library precompile) then elaborate to the reusable simv, folded into one
            # `hdl_compile` stage. The analyze sub-step keeps the primary stage log/script; the
            # elaborate sub-step writes alongside it so neither sub-step's evidence is
            # overwritten, and a failing elaborate points the result at its own log.
            rc = vcs_analyze(flow, root, sim_cfg, args, log_path, script_path, env_path)
            if rc == 0:
                elab_log = stage_dir / "logs" / f"{stage_suffix}.elaborate.log"
                elab_script = stage_dir / "scripts" / f"{stage_suffix}.elaborate.sh"
                elab_env = stage_dir / "env" / f"{stage_suffix}.elaborate.env"
                rc = vcs_build(
                    flow,
                    root,
                    sim_cfg,
                    args,
                    elab_log,
                    elab_script,
                    elab_env,
                    include_filelist=False,
                )
                if rc != 0:
                    log_path = elab_log
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
            sim_args = _sim_test_args(
                sim_cfg,
                selected_run_mode(sim_cfg, catalog.tests[item], args),
                catalog.tests[item],
                args,
                seed,
                root,
            )
            rc = vcs_sim(
                flow,
                root,
                sim_cfg,
                catalog,
                item,
                args,
                stage_dir,
                log_path,
                script_path,
                env_path,
                seed,
                test_args=sim_args,
            )
            info = _vcs_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="vcs",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
            _stamp_provenance(
                root,
                log_path,
                metadata,
                fingerprint=str(info.get("fingerprint", "")) or None,
                filelist=None,
                dry_run=bool(args.dry_run),
                sim_args=sim_args,
                cwd=stage_dir,
            )
        elif kind == "xrun_filelist":
            rc = generate_filelist(
                flow,
                root,
                sim_cfg,
                args.dry_run,
                log_path,
                script_path,
                env_path,
                args.quiet,
                verbose=args.verbose,
            )
        elif kind == "xrun_analyze":
            rc = xcelium_analyze(flow, root, sim_cfg, args, log_path, script_path, env_path)
        elif kind == "xrun_compile":
            rc = xcelium_build(
                flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=True
            )
            info = _xcelium_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="xcelium",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        elif kind == "xrun_elaborate":
            rc = xcelium_build(
                flow, root, sim_cfg, args, log_path, script_path, env_path, include_filelist=False
            )
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
            rc = xcelium_sim(
                flow,
                root,
                sim_cfg,
                catalog,
                item,
                args,
                stage_dir,
                log_path,
                script_path,
                env_path,
                seed,
            )
            info = _xcelium_resolve_build(flow, root, sim_cfg, args)
            metadata["target_build"] = _target_build_metadata(
                target_name=info["target_name"],
                tool="xcelium",
                build_dir=info["build_dir"],
                fingerprint=info["fingerprint"],
            )
        else:
            raise ConfigError(f"{flow.path}: unsupported native stage kind `{kind}`")

        if stage_name in {"sim", "regress"} and item is not None and args.cov:
            tool_cov = coverage_cfg(sim_cfg).get(tool, {})
            if not isinstance(tool_cov, dict):
                raise ConfigError(f"coverage.{tool} must be a table")
            native_coverage = coverage_artifact_path(tool_cov, stage_dir / "coverage")
            target_build = metadata.get("target_build")
            fingerprint = (
                target_build.get("fingerprint") if isinstance(target_build, dict) else None
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

        if stage_name in {"hdl_compile", "elaborate"} and args.cov and tool == "vcs":
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
        if (
            rc != 0
            and stage_name == "cov_report"
            and log_path.is_file()
            and "COVERAGE THRESHOLD:" in log_path.read_text(encoding="utf-8", errors="replace")
        ):
            bucket_kind = "coverage_threshold"
            reason = "coverage threshold not met"
        buckets = (
            None
            if rc == 0
            else [
                {
                    "kind": bucket_kind,
                    "signature": reason,
                    "count": 1,
                    "examples": [repo_rel(root, log_path)],
                }
            ]
        )
        parser = None
        if stage_name == "formal" and item is not None and not args.dry_run:
            app = resolve_formal_app(flow, root, sim_cfg, catalog, item, args, tool)
            formal_decision = grade_formal_stage(
                root=root,
                tool=app.tool,
                simulators=simulators,
                policies=policies,
                item=item,
                app_name=app.name,
                app_table=app.table,
                cwd=app.cwd,
                stage_dir=stage_dir,
                run_dir=run_dir,
                log_path=log_path,
                return_code=rc,
            )
            status = formal_decision.status
            reason = formal_decision.reason
            buckets = formal_decision.failure_buckets or None
            parser = formal_decision.parser
            formal_report = formal_decision.formal
            console.event("formal", f"{item}: {reason}")
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
        buckets = [
            {
                "kind": "timeout",
                "signature": reason[:120],
                "count": 1,
                "examples": [repo_rel(root, log_path)],
            }
        ]
        parser = None
        console.event("error", reason)
    except Exception as exc:
        rc = 2
        status = "ERROR"
        reason = str(exc)
        # Cause-based bucketing: a config problem is a config_error no matter which stage it
        # surfaced in; only unclassified process failures fall back to the per-stage default.
        bucket_kind = (
            "config_error"
            if isinstance(exc, ConfigError)
            else FAILURE_BUCKET_BY_STAGE.get(stage_name, "tool_error")
        )
        buckets = [
            {
                "kind": bucket_kind,
                "signature": reason[:120],
                "count": 1,
                "examples": [repo_rel(root, log_path)],
            }
        ]
        parser = None
        console.event("error", reason)

    expect_fail = (
        catalog.tests[item].expect_fail
        if stage_name in {"sim", "regress"}
        and item is not None
        and item in catalog.tests
        and not args.dry_run
        else None
    )
    if expect_fail:
        status, reason, buckets, metadata["expected_fail"] = grade_expected_fail(
            status,
            reason,
            buckets,
            expect_fail,
            observed_failures=xunit_failure_messages(stage_dir / "results" / "results.xml"),
            expect_fail_match=catalog.tests[item].expect_fail_match,
        )
        for bucket in buckets or []:
            examples = bucket.setdefault("examples", [])
            rel_log = repo_rel(root, log_path)
            if rel_log and rel_log not in examples:
                examples.append(rel_log)
        console.event("xfail", f"{item}: {reason}")

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
                manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
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
        if (run_dir / "cov" / "report_raw").is_dir():
            artifacts["coverage_report_raw"] = repo_rel(root, run_dir / "cov" / "report_raw")
        if summary_path.is_file():
            artifacts["coverage_summary"] = repo_rel(root, summary_path)
        if details_path.is_file():
            artifacts["coverage_details"] = repo_rel(root, details_path)
        if raw_details_path.is_file():
            artifacts["coverage_details_raw"] = repo_rel(root, raw_details_path)
        if application_path.is_file():
            artifacts["coverage_policy_application"] = repo_rel(root, application_path)
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
        dump_script = {
            "vcs": stage_dir / "scripts" / f"waves.{item}.ucli",
            "xcelium": stage_dir / "scripts" / f"waves.{item}.tcl",
        }.get(tool)
        if dump_script is not None and (args.dry_run or dump_script.is_file()):
            wave_meta["dump_script"] = repo_rel(root, dump_script) or str(dump_script)
            artifacts["wave_dump_script"] = wave_meta["dump_script"]
        if not args.dry_run and not wave_files and wave_meta.get("retention_action") == "kept":
            wave_meta["warning"] = (
                f"waves were requested (format `{wave_format}`) but the simulation produced "
                f"no {wave_format} file; check the wave dump script and the simulation log"
            )
            console.event("warning", wave_meta["warning"], force=True)
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
    result = StageResult(
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
        target=target_name
        if stage_name in {"flist", "hdl_compile", "elaborate", "sim", "regress"}
        else None,
        formal=formal_report,
    )
    # Structured-result guarantee: every executed leaf ends with results/results.xml —
    # the framework's own file when it wrote one, a synthesized single-testcase file
    # otherwise. Runs after classification and must never affect status or exit.
    if stage_name in {"sim", "regress"} and item is not None and not args.dry_run:
        try:
            native_xml = stage_dir / "results" / "results.xml"
            if native_xml.is_file():
                artifacts["results_xml"] = repo_rel(root, native_xml)
            else:
                generated = ensure_leaf_junit(
                    flow=flow,
                    root=root,
                    run_dir=run_dir,
                    tool=tool,
                    result=result,
                    leaf_dir=stage_dir,
                )
                if generated is not None:
                    artifacts["results_xml"] = repo_rel(root, generated)
        except Exception as exc:  # noqa: BLE001
            console.event("warning", f"junit synthesis failed for {item}: {exc}", force=True)
    return result
