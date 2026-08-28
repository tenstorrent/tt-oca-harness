# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Build acceleration knobs, object cache, and a fingerprinted build cache.

All behavior here is opt-in via the DUT `[build.options]` and `[build.cache]` config tables so a
contributor controls the full stack:

`[build.options]` carries simulator-neutral knobs (OD-19 folded the former `[build.cache]` in here):

- build acceleration — parallel build (`build_jobs`) and dev-time `cflags` (e.g. ``-O0``).
  Tool-specific acceleration, such as Verilator `output_split` and `ccache`, lives under
  `[build.<tool>]`.
- fingerprinted build cache — `cache_enabled` partitions the build directory by an input
  fingerprint so different configs do not clobber each other and an unchanged config reuses its
  build; `rebuild` forces a clean build; `cache_key_extra` folds extra strings into the
  fingerprint. Within one fingerprint dir, the tool's own dependency tracking handles incremental
  source edits. Verilator re-verilates from ``Vtop__ver.d``. VCS cocotb ``make compile`` has no
  filelist deps (sources arrive via ``-f``), so the runner adds ``[build].top_file`` plus
  ``[build].sources``, ``[build].stubs`` and every header under ``[build].incdirs`` to
  ``CUSTOM_COMPILE_DEPS``, and ``--rebuild`` wipes that ``sim_build`` tree. The RTL the
  bender filelist names is still NOT tracked -- it arrives as one ``-f`` line and the
  fingerprint hashes the filelist text, not the files' content, so editing it needs
  ``--rebuild``. See `vcs_simv_compile_deps`.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Sequence

from .config import as_int, as_str_list, config_section

_BINARY_VERSION: dict[str, str] = {}


def build_options_cfg(build: dict[str, Any]) -> dict[str, Any]:
    return config_section(build, "options")


def build_verilator_cfg(build: dict[str, Any]) -> dict[str, Any]:
    return config_section(build, "verilator")


def build_vcs_cfg(build: dict[str, Any]) -> dict[str, Any]:
    return config_section(build, "vcs")


def build_xcelium_cfg(build: dict[str, Any]) -> dict[str, Any]:
    return config_section(build, "xcelium")


def effective_build_jobs(options: dict[str, Any], jobs: int) -> int:
    """Config `build_jobs` wins; otherwise inherit CLI ``--build-jobs``/``--sim-jobs``."""
    configured = as_int(options.get("build_jobs"), "build.options.build_jobs") or 0
    if configured > 0:
        return configured
    return jobs if jobs and jobs > 1 else 0


def option_build_args(options: dict[str, Any], verilator_cfg: dict[str, Any], jobs: int) -> list[str]:
    """Translate shared options plus `[build.verilator]` into Verilator build arguments."""
    extra: list[str] = []
    build_jobs = effective_build_jobs(options, jobs)
    if build_jobs > 0:
        extra += ["--build-jobs", str(build_jobs)]
    split = as_int(verilator_cfg.get("output_split"), "build.verilator.output_split") or 0
    if split > 0:
        extra += ["--output-split", str(split)]
    cflags = str(options.get("cflags", "")).strip()
    for token in cflags.split():
        extra += ["-CFLAGS", token]
    extra += as_str_list(verilator_cfg.get("extra_args"), "build.verilator.extra_args")
    return extra


def apply_option_env(options: dict[str, Any], env: dict[str, str], verilator_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Enable ccache as Verilator's object cache when requested (Verilator-only)."""
    cfg = verilator_cfg or {}
    if bool(cfg.get("ccache", False)):
        env.setdefault("OBJCACHE", "ccache")
    return env


def vcs_build_args(options: dict[str, Any], vcs_cfg: dict[str, Any], jobs: int) -> list[str]:
    """Translate the shared `[build.options]` and VCS-specific `[build.vcs]` knobs into VCS flags.

    Mapping of the cross-tool knobs to VCS (vs the Verilator equivalents):
    - ``build_jobs`` -> ``-j<N>`` (parallel native compile)        [Verilator: --build-jobs]
    - ``cflags``     -> ``-CFLAGS <flag>``                          [Verilator: -CFLAGS]
    - ``ccache``     -> ignored; VCS uses incremental/partition compile instead of ccache
    - ``output_split`` -> ignored; the VCS analogue is partition compile below
    VCS-only (`[build.vcs]`):
    - ``partition_compile`` -> ``-partcomp`` / ``-partcomp=autopart_<low|medium|high>``
    - ``opt_level``         -> raw VCS optimization flag, e.g. ``-O0`` for fast dev builds
    - ``extra_args``        -> appended verbatim
    """
    extra: list[str] = []
    build_jobs = effective_build_jobs(options, jobs)
    if build_jobs > 0:
        extra.append(f"-j{build_jobs}")

    part = vcs_cfg.get("partition_compile", False)
    if part is True:
        extra.append("-partcomp")
    elif isinstance(part, str) and part:
        extra.append(f"-partcomp=autopart_{part}" if part in {"low", "medium", "high"} else part)

    opt = str(vcs_cfg.get("opt_level", "")).strip()
    if opt:
        extra.append(opt)

    cflags = str(options.get("cflags", "")).strip()
    for token in cflags.split():
        extra += ["-CFLAGS", token]

    extra += as_str_list(vcs_cfg.get("extra_args"), "build.vcs.extra_args")
    return extra


def xcelium_build_args(options: dict[str, Any], xcelium_cfg: dict[str, Any], jobs: int) -> list[str]:
    """Translate `[build.options]` + `[build.xcelium]` into Xcelium elaboration (xmelab/xrun) flags.

    - ``build_jobs`` -> ``-mce -mce_build_thread_count <N>`` (multi-core build)  [Verilator: --build-jobs; VCS: -j]
    - ``cflags``     -> ``-Wcxx,<flag>``                                          [Verilator/VCS: -CFLAGS]
    - ``ccache`` / ``output_split`` -> ignored; Xcelium uses multi-core + incremental elaboration
    Xcelium-only (`[build.xcelium]`):
    - ``mce`` (bool)        -> force ``-mce`` even without a thread count
    - ``opt_level``         -> raw optimization flag passthrough
    - ``extra_args``        -> appended verbatim
    """
    extra: list[str] = []
    build_jobs = effective_build_jobs(options, jobs)
    if build_jobs > 0:
        extra += ["-mce", "-mce_build_thread_count", str(build_jobs)]
    elif bool(xcelium_cfg.get("mce", False)):
        extra.append("-mce")

    opt = str(xcelium_cfg.get("opt_level", "")).strip()
    if opt:
        extra.append(opt)

    cflags = str(options.get("cflags", "")).strip()
    for token in cflags.split():
        extra.append(f"-Wcxx,{token}")

    extra += as_str_list(xcelium_cfg.get("extra_args"), "build.xcelium.extra_args")
    return extra


def binary_version(binary: str, version_args: list[str], root: Path) -> str:
    key = f"{binary}:{root}"
    if key in _BINARY_VERSION:
        return _BINARY_VERSION[key]
    version = "unknown"
    if shutil.which(binary):
        try:
            proc = subprocess.run([binary, *version_args], cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)
            line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
            version = line or "unknown"
        except (OSError, subprocess.SubprocessError):
            version = "unknown"
    _BINARY_VERSION[key] = version
    return version


def verilator_version(root: Path) -> str:
    return binary_version("verilator", ["--version"], root)


def vcs_version(root: Path) -> str:
    return binary_version("vcs", ["-ID"], root)


def xcelium_version(root: Path) -> str:
    return binary_version("xrun", ["-version"], root)


def vcs_simv_compile_deps(
    top_file: Path | None, local_sources: Sequence[Path] = ()
) -> list[str]:
    """Makefile lines that make ``$(SIM_BUILD)/simv`` depend on the repo-local build inputs.

    Cocotb's VCS recipe is ``$(SIM_BUILD)/simv: $(VERILOG_SOURCES) ... $(CUSTOM_COMPILE_DEPS)``.
    ``VERILOG_SOURCES`` is empty when the DUT is passed via ``COMPILE_ARGS += -f <filelist>``,
    so without these extra deps ``make compile`` is existence-only and an edit to a file the
    filelist names is ignored. Verilator does not need this: ``Vtop__ver.d`` lists them already.

    ``build_fingerprint`` hashes the filelist TEXT, so it moves when a path is added or removed
    but not when a named file's CONTENT changes. The deps here are what cover content edits.

    Covered: ``[build].top_file`` plus ``[build].sources`` and ``[build].stubs`` (the repo-local
    override/additive sources -- ``tb_top.sv``, the mem responders, the protocol SVA).

    NOT covered, and still needing ``--rebuild`` after an edit:

    * the bender-generated filelist's own RTL: it arrives as a single ``-f`` line and
      ``build_fingerprint`` hashes the filelist TEXT, so a content-only edit moves
      neither the deps nor the fingerprint.

    Headers under ``[build].incdirs`` ARE covered -- ``_vcs_local_sources`` globs them,
    because an ``+incdir+`` has no file list of its own and an assertion-macro header is
    edited far more often than the RTL that includes it.
    """
    deps = [] if top_file is None else [top_file]
    deps.extend(local_sources)
    return [f"CUSTOM_COMPILE_DEPS += {path}" for path in deps]


# One VCS ``sim_build`` is shared by every leaf of a target, and leaves run on a
# thread pool -- see vcs_force_rebuild().
_FORCE_REBUILD_LOCK = threading.Lock()
_FORCE_REBUILT: set[str] = set()


def vcs_force_rebuild(sim_build: Path) -> None:
    """Drop a VCS ``sim_build`` tree so ``make compile`` cannot treat ``simv`` as up to date.

    This is what ``--rebuild`` means for the VCS cocotb flow. Verilator and Xcelium go through
    cocotb's Python runner and get the same effect from ``runner.build(always=rebuild)``; VCS
    shells out to ``make``, which has no such knob, so the tree is removed instead.

    Serialised and once-only, because every leaf of a target SHARES one ``sim_build``.
    Leaves run on a thread pool, so without this ``--stage sim --rebuild -j8`` lets one
    leaf delete ``csrc/`` while another is mid-compile in it, or remove a ``simv`` a third
    is about to exec. The intent is "this invocation compiles from scratch", not "every
    leaf wipes the tree", so the first caller removes it and the rest no-op.

    A concurrent delete is tolerated rather than fatal: raising here would abort the whole
    run instead of failing one leaf.
    """
    with _FORCE_REBUILD_LOCK:
        key = str(sim_build)
        if key in _FORCE_REBUILT:
            return
        _FORCE_REBUILT.add(key)
        if sim_build.is_dir():
            shutil.rmtree(sim_build, ignore_errors=True)


def build_fingerprint(*, build_args: list[str], top_module: str, tool_version: str, filelist_text: str, extra: list[str]) -> str:
    """Stable 12-hex digest over the declared build inputs (not per-seed)."""
    hasher = hashlib.sha256()
    for part in (top_module, tool_version, filelist_text, *build_args, *extra):
        hasher.update(str(part).encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()[:12]


def resolve_build_dir(base: Path, options: dict[str, Any], fingerprint: str) -> Path:
    """Partition the build dir by fingerprint when the cache is enabled; else use the base dir."""
    if bool(options.get("cache_enabled", False)):
        return base / fingerprint
    return base


def cache_key_extra(options: dict[str, Any]) -> list[str]:
    return as_str_list(options.get("cache_key_extra"), "build.options.cache_key_extra")
