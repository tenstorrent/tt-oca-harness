# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Executors: where a leaf attempt runs.

The registry (``executors.toml`` merged with the site layer) names executors; this package
turns a name into a driver. ``local`` runs attempts in-process. A cluster table selects one
of :data:`~runlib.config.CLUSTER_DRIVERS`, and the generic :class:`ClusterExecutor` runs the
table's argv templates with that driver's :class:`SchedulerDialect` reading the output. An
entry whose driver has no dialect here validates and shows in ``--doctor`` but cannot
dispatch, so a site keeps its scheduler configuration in the registry independently of the
driver code.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..config import CLUSTER_DRIVERS, EXECUTOR_LIMIT_KEYS, as_str_list
from ..models import ConfigError
from ..site import ToolLaunch, launch_env
from .base import (
    ExecutionResult,
    Executor,
    JobHandle,
    JobObservation,
    JobState,
    LeafTask,
    ResourceRequest,
    error_result,
    render_argv,
    resolve_resources,
    result_from_fragment,
    task_identifier,
)
from .cluster import ClusterError, ClusterExecutor, SchedulerDialect
from .local import AttemptRunner, LocalExecutor
from .lsf import LsfDialect
from .slurm import SlurmDialect

LOCAL_DRIVER = "local"
DIALECTS: dict[str, type[SchedulerDialect]] = {
    LsfDialect.driver: LsfDialect,
    SlurmDialect.driver: SlurmDialect,
}
IMPLEMENTED_DRIVERS = frozenset({LOCAL_DRIVER, *DIALECTS})
NOT_IMPLEMENTED = "is configured but the runner has no driver for it"

# Values the coordinator loop uses for a limit the registry leaves unset. The local executor
# answers `wait` as soon as an attempt ends, so its poll interval only bounds a quiet wait.
DEFAULT_LIMITS: dict[str, Any] = {
    "max_in_flight": None,
    "submit_batch_size": 1,
    "query_batch_size": 100,
    "poll_interval_sec": 10.0,
    "artifact_grace_sec": 60.0,
    "cancel_grace_sec": 3.0,
    "command_timeout_sec": 120.0,
    "array_chunk_size": 100,
}
# A scheduler answers a cancel or a query in seconds, not milliseconds, and one query covers
# every submission since the previous one. An array chunk stays well inside the array size
# both schedulers allow by default (LSF MAX_JOB_ARRAY_SIZE 1000, Slurm MaxArraySize 1001).
CLUSTER_DEFAULT_LIMITS: dict[str, Any] = {
    **DEFAULT_LIMITS,
    "submit_batch_size": 25,
    "cancel_grace_sec": 30.0,
}


def executor_driver(cfg: Mapping[str, Any]) -> str:
    """The driver an executor table selects; a schema-1 cluster table selects none."""
    if cfg.get("kind") == "local":
        return LOCAL_DRIVER
    return str(cfg.get("driver") or "")


def dispatch_blocker(name: str, cfg: Mapping[str, Any]) -> str | None:
    """Why ``name`` cannot dispatch here, or None when it can."""
    driver = executor_driver(cfg)
    if driver == LOCAL_DRIVER:
        return None
    dialect = DIALECTS.get(driver)
    if dialect is None:
        return f"executor `{name}` {NOT_IMPLEMENTED}"
    parser = cfg.get("history_parser")
    if cfg.get("history_argv") and parser not in dialect.history_parsers:
        known = ", ".join(sorted(dialect.history_parsers)) or "none"
        return (
            f"executor `{name}` names history_parser {parser!r}; driver `{driver}` "
            f"implements: {known}"
        )
    return None


def executor_limits(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The `limits` table with the defaults filled in."""
    out = dict(DEFAULT_LIMITS if executor_driver(cfg) == LOCAL_DRIVER else CLUSTER_DEFAULT_LIMITS)
    table = cfg.get("limits") or {}
    for key in EXECUTOR_LIMIT_KEYS:
        if key in table:
            out[key] = table[key]
    return out


def executor_environment(name: str, cfg: Mapping[str, Any]) -> dict[str, str]:
    """The environment the executor's scheduler commands run in, after its ``setup_hook``."""
    binaries = as_str_list(cfg.get("binaries"), f"{name}.binaries")
    hook = cfg.get("setup_hook")
    launch = ToolLaunch(
        tool=name,
        binary=binaries[0] if binaries else name,
        setup_hook=Path(str(hook)) if hook else None,
    )
    return launch_env(launch)


def missing_binaries(cfg: Mapping[str, Any], env: Mapping[str, str]) -> list[str]:
    binaries = as_str_list(cfg.get("binaries"), "binaries")
    return [binary for binary in binaries if shutil.which(binary, path=env.get("PATH")) is None]


def build_executor(
    name: str,
    cfg: Mapping[str, Any],
    *,
    runner: AttemptRunner,
    max_workers: int,
    root: Path | None = None,
    run_dir: Path | None = None,
    on_event: Callable[[str], None] | None = None,
) -> Executor:
    """The executor for registry entry ``name``, ready to submit."""
    blocker = dispatch_blocker(name, cfg)
    if blocker:
        raise ConfigError(blocker)
    driver = executor_driver(cfg)
    if driver == LOCAL_DRIVER:
        return LocalExecutor(name, runner, max_workers=max_workers)
    if root is None or run_dir is None:
        raise ConfigError(f"executor `{name}` needs the repository root and run directory")
    env = executor_environment(name, cfg)
    missing = missing_binaries(cfg, env)
    if missing:
        raise ConfigError(
            f"executor `{name}` cannot find {', '.join(missing)} on PATH"
            + (" after sourcing setup_hook" if cfg.get("setup_hook") else "")
        )
    return ClusterExecutor(
        name,
        cfg,
        DIALECTS[driver](),
        root=root,
        run_dir=run_dir,
        limits=executor_limits(cfg),
        env=env,
        on_event=on_event,
    )


__all__ = [
    "CLUSTER_DEFAULT_LIMITS",
    "CLUSTER_DRIVERS",
    "DEFAULT_LIMITS",
    "DIALECTS",
    "IMPLEMENTED_DRIVERS",
    "LOCAL_DRIVER",
    "NOT_IMPLEMENTED",
    "AttemptRunner",
    "ClusterError",
    "ClusterExecutor",
    "ExecutionResult",
    "Executor",
    "JobHandle",
    "JobObservation",
    "JobState",
    "LeafTask",
    "LocalExecutor",
    "ResourceRequest",
    "SchedulerDialect",
    "build_executor",
    "dispatch_blocker",
    "error_result",
    "executor_driver",
    "executor_environment",
    "executor_limits",
    "missing_binaries",
    "render_argv",
    "resolve_resources",
    "result_from_fragment",
    "task_identifier",
]
