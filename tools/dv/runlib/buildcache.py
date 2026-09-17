# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Build acceleration knobs, object cache, and a fingerprinted build cache.

All behavior here is opt-in via the DUT `[build.options]` config table so a contributor controls
the full stack:

`[build.options]` carries simulator-neutral knobs:

- build acceleration — parallel build (`build_jobs`) and dev-time `cflags` (e.g. ``-O0``).
  Tool-specific acceleration, such as Verilator `output_split` and `ccache`, lives under
  `[build.<tool>]`.
- fingerprinted build cache — `cache_enabled` partitions the build directory by an input
  fingerprint so different configs do not clobber each other and an unchanged config reuses its
  build; `rebuild` forces a clean build; `cache_key_extra` folds extra strings into the
  fingerprint. The fingerprint covers the build arguments, the filelist text and a content
  digest over the sources the bender filelist names, so an RTL or testbench edit moves the
  build into a fresh directory; `rebuild` (``--rebuild``) forces a clean build of the current
  one through the cocotb runner's ``always`` flag on every simulator.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

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


def option_build_args(
    options: dict[str, Any], verilator_cfg: dict[str, Any], jobs: int
) -> list[str]:
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


def apply_option_env(
    options: dict[str, Any], env: dict[str, str], verilator_cfg: dict[str, Any] | None = None
) -> dict[str, str]:
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


def xcelium_build_args(
    options: dict[str, Any], xcelium_cfg: dict[str, Any], jobs: int
) -> list[str]:
    """Translate `[build.options]` + `[build.xcelium]` into Xcelium elaboration (xmelab/xrun) flags.

    - ``cflags``     -> ``-Wcxx,<flag>``                                          [Verilator/VCS: -CFLAGS]
    - ``ccache`` / ``output_split`` -> ignored; Xcelium uses incremental elaboration
    Xcelium-only (`[build.xcelium]`):
    - ``mce`` (bool)        -> ``-mce``, and ``build_jobs`` then sets its thread count
    - ``opt_level``         -> raw optimization flag passthrough
    - ``extra_args``        -> appended verbatim

    ``build_jobs`` does not reach Xcelium on its own. On Verilator and VCS it is
    a build-time knob (``--build-jobs`` / ``-j``); the nearest Xcelium option is
    ``-mce``, which turns on the Multi-Core Engine for the *simulation* and so
    makes ``xmsim`` check out an ``Xcelium_Multi_Core`` feature instead of
    ``Xcelium_Single_Core``. A single-core entitlement cannot run under ``-mce``,
    so only ``[build.xcelium] mce`` requests it.
    """
    extra: list[str] = []
    if bool(xcelium_cfg.get("mce", False)):
        extra.append("-mce")
        build_jobs = effective_build_jobs(options, jobs)
        if build_jobs > 0:
            extra += ["-mce_build_thread_count", str(build_jobs)]

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
            proc = subprocess.run(
                [binary, *version_args],
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
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


def build_fingerprint(
    *,
    build_args: list[str],
    top_module: str,
    tool_version: str,
    filelist_text: str,
    extra: list[str],
) -> str:
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
