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
  one.

The build stamp is not opt-in. Every compile that succeeds writes ``ocah_build.json`` into the
build directory it produced, recording the artifact digest, the commit and the tool version the
artifact was compiled from. Before a compile the runner reads that stamp back: a digest that
matches means the artifact on disk was built from exactly these inputs and may be reused, and any
other answer -- a different digest, or no stamp at all -- is a stale or unattributable artifact
that gets cleaned and rebuilt. The stamp travels into every per-test result as the
`build_identity` / `build_commit` pair, so a reader can tell a fresh compile from a reused one
without reconstructing it from file timestamps.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC
from .config import as_int, as_str_list, config_section
from .models import ConfigError

_BINARY_VERSION: dict[str, str] = {}
_GIT_HEAD: dict[str, dict[str, str]] = {}

BUILD_STAMP_NAME = "ocah_build.json"
BUILD_STAMP_SCHEMA = 1

# One id per `run_dv.py` process, so a stamp says whether this run compiled the artifact.
BUILD_SESSION = uuid.uuid4().hex[:12]


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


def command_text(argv: list[str], root: Path) -> str:
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip()


def git_head(root: Path) -> dict[str, str]:
    """The checkout's commit and dirty flag, sampled once per process per root."""
    key = str(root)
    cached = _GIT_HEAD.get(key)
    if cached is None:
        cached = {
            "commit": command_text(["git", "rev-parse", "HEAD"], root),
            "dirty": "true" if command_text(["git", "status", "--porcelain"], root) else "false",
        }
        _GIT_HEAD[key] = cached
    return dict(cached)


def build_stamp_path(build_dir: Path) -> Path:
    return Path(build_dir) / BUILD_STAMP_NAME


def read_build_stamp(build_dir: Path) -> dict[str, Any] | None:
    path = build_stamp_path(build_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_build_stamp(
    build_dir: Path,
    *,
    root: Path,
    artifact_digest: str,
    fingerprint: str,
    target: str,
    tool: str,
    tool_version: str,
) -> dict[str, Any]:
    """Record what produced the artifact now sitting in `build_dir`."""
    head = git_head(root)
    stamp: dict[str, Any] = {
        "schema_version": BUILD_STAMP_SCHEMA,
        "artifact_digest": artifact_digest,
        "fingerprint": fingerprint,
        "target": target,
        "tool": tool,
        "tool_version": tool_version,
        "commit": head["commit"],
        "dirty": head["dirty"],
        "built_at": datetime.now(UTC).isoformat(),
        "session": BUILD_SESSION,
    }
    path = build_stamp_path(build_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    try:
        temporary.write_text(json.dumps(stamp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return stamp


def build_identity(stamp: dict[str, Any] | None, artifact_digest: str) -> str:
    """Whether the artifact in the stamped directory answers for `artifact_digest`.

    - ``unrecorded``: nothing in the directory says what produced it.
    - ``stale``: it was produced from different inputs than the ones being built now.
    - ``fresh``: this process compiled it.
    - ``reused``: an earlier run compiled it from these exact inputs.
    """
    if not stamp or not str(stamp.get("artifact_digest") or ""):
        return "unrecorded"
    if str(stamp.get("artifact_digest")) != artifact_digest:
        return "stale"
    return "fresh" if str(stamp.get("session") or "") == BUILD_SESSION else "reused"


def build_provenance(stamp: dict[str, Any] | None, artifact_digest: str) -> dict[str, Any]:
    """The identity fields a result record carries so a reader need not reconstruct them."""
    identity = build_identity(stamp, artifact_digest)
    provenance: dict[str, Any] = {
        "artifact_digest": artifact_digest,
        "build_identity": identity,
        "build_commit": None,
        "build_dirty": None,
        "built_at": None,
        "build_tool_version": None,
    }
    if stamp:
        provenance["build_commit"] = str(stamp.get("commit") or "") or None
        provenance["build_dirty"] = str(stamp.get("dirty") or "") or None
        provenance["built_at"] = str(stamp.get("built_at") or "") or None
        provenance["build_tool_version"] = str(stamp.get("tool_version") or "") or None
    return provenance


def clean_build_dir(build_dir: Path, root: Path) -> bool:
    """Delete a build directory so no part of the previous artifact can survive into the next one.

    Verilator's `--skip-identical` and `make`'s timestamp check both decide reuse from the state
    of this directory, and cocotb's Verilator runner drops the `always` flag, so emptying the
    directory is the only tool-neutral way to make a forced rebuild actually compile.
    """
    target = Path(build_dir).resolve()
    repo = Path(root).resolve()
    refused = {repo, Path(target.anchor), Path.home().resolve()}
    if target in refused or target in repo.parents:
        raise ConfigError(f"[build] build_dir is not a directory the runner may clean: {target}")
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
