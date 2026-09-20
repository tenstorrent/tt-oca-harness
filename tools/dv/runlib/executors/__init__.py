# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Executors: where a leaf attempt runs.

The registry (``executors.toml`` merged with the site layer) names executors; this package
turns a name into a driver. ``local`` runs attempts in-process. A cluster table selects one
of :data:`~runlib.config.CLUSTER_DRIVERS`. An entry whose driver is absent from
:data:`IMPLEMENTED_DRIVERS` validates and shows in ``--doctor`` but cannot dispatch, so a
site keeps its scheduler configuration in the registry independently of the driver code.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import CLUSTER_DRIVERS, EXECUTOR_LIMIT_KEYS
from ..models import ConfigError
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
from .local import AttemptRunner, LocalExecutor

LOCAL_DRIVER = "local"
IMPLEMENTED_DRIVERS = frozenset({LOCAL_DRIVER})
NOT_IMPLEMENTED = "is configured but non-local dispatch is not implemented"

# Values the coordinator loop uses for a limit the registry leaves unset.
DEFAULT_LIMITS: dict[str, Any] = {
    "max_in_flight": None,
    "submit_batch_size": 1,
    "query_batch_size": 100,
    "poll_interval_sec": 10.0,
    "artifact_grace_sec": 60.0,
    "cancel_grace_sec": 3.0,
}


def executor_driver(cfg: Mapping[str, Any]) -> str:
    """The driver an executor table selects; a schema-1 cluster table selects none."""
    if cfg.get("kind") == "local":
        return LOCAL_DRIVER
    return str(cfg.get("driver") or "")


def dispatch_blocker(name: str, cfg: Mapping[str, Any]) -> str | None:
    """Why ``name`` cannot dispatch here, or None when it can."""
    driver = executor_driver(cfg)
    if driver in IMPLEMENTED_DRIVERS:
        return None
    return f"executor `{name}` {NOT_IMPLEMENTED}"


def executor_limits(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The `limits` table with the defaults filled in."""
    out = dict(DEFAULT_LIMITS)
    table = cfg.get("limits") or {}
    for key in EXECUTOR_LIMIT_KEYS:
        if key in table:
            out[key] = table[key]
    return out


def build_executor(
    name: str,
    cfg: Mapping[str, Any],
    *,
    runner: AttemptRunner,
    max_workers: int,
) -> Executor:
    """The executor for registry entry ``name``, ready to submit."""
    blocker = dispatch_blocker(name, cfg)
    if blocker:
        raise ConfigError(blocker)
    return LocalExecutor(name, runner, max_workers=max_workers)


__all__ = [
    "CLUSTER_DRIVERS",
    "DEFAULT_LIMITS",
    "IMPLEMENTED_DRIVERS",
    "LOCAL_DRIVER",
    "NOT_IMPLEMENTED",
    "AttemptRunner",
    "ExecutionResult",
    "Executor",
    "JobHandle",
    "JobObservation",
    "JobState",
    "LeafTask",
    "LocalExecutor",
    "ResourceRequest",
    "build_executor",
    "dispatch_blocker",
    "error_result",
    "executor_driver",
    "executor_limits",
    "render_argv",
    "resolve_resources",
    "result_from_fragment",
    "task_identifier",
]
