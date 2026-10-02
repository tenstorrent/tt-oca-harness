# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The leaf manifest and the one attempt it describes.

A manifest is the whole brief a worker receives: which DUT, tool, stage, item, seed and
attempt to run, where the run tree lives, and the command line the coordinator ran with. Its
``plan_digest`` covers every other key, so a worker refuses a manifest that was edited or
truncated. :func:`execute_attempt` is the body both the local executor and the worker entry
point run: exactly one ``run_stage`` and the leaf's ``result.json``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..models import ConfigError, Flow, StageResult, TestCatalog
from ..paths import repo_rel
from ..results import fragment_payload, write_result
from ..stages import run_stage
from .base import LEAF_ROLE, LeafTask, ResourceRequest, now_iso

MANIFEST_SCHEMA_VERSION = 1
DIGEST_KEY = "plan_digest"
# Command-line attributes an attempt may override; anything else in the manifest's overrides
# is a refusal, so a manifest cannot redirect a worker to another DUT or run directory.
OVERRIDABLE_ARGS = frozenset(
    {
        "waves",
        "waves_on_fail",
        "wave_start",
        "wave_end",
        "wave_window",
        "wave_margin",
        "wave_retention",
        "ui",
        "quiet",
        "verbose",
    }
)


class ManifestError(ConfigError):
    """A manifest that cannot be trusted or cannot be run here."""


def jobs_dir(run_dir: Path) -> Path:
    return run_dir / "stages" / "regress" / "jobs"


def manifest_path(run_dir: Path, task_id: str) -> Path:
    return jobs_dir(run_dir) / f"{task_id}.json"


def completion_path(run_dir: Path, task_id: str) -> Path:
    return jobs_dir(run_dir) / f"{task_id}.done.json"


def clear_attempt_outputs(task: LeafTask) -> None:
    """Remove the leaf ``result.json``, the completion record and the JUnit files under
    ``results/`` from the attempt's paths.

    Task ids and flat leaf directories repeat across invocations into one run directory, so
    whatever sits at these paths before the attempt runs was written by an earlier one.
    """
    task.result_json.unlink(missing_ok=True)
    completion_path(task.run_dir, task.task_id).unlink(missing_ok=True)
    results = task.leaf_dir / "results"
    if results.is_dir():
        for path in results.glob("*.xml"):
            if path.is_file():
                path.unlink(missing_ok=True)


def repo_identity(root: Path) -> tuple[str | None, bool | None]:
    """(HEAD commit, dirty flag) of the checkout, or Nones when git cannot answer."""
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if head.returncode != 0:
        return None, None
    commit = head.stdout.strip() or None
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return commit, dirty


def manifest_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != DIGEST_KEY}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_payload(
    task: LeafTask,
    *,
    flow: Flow,
    root: Path,
    tool: str,
    executor: str,
    argv: list[str],
    ui_leaf_mode: str,
    multi_target: bool,
    overlay: Path | None,
    site: Path | None,
    repo_commit: str | None,
    repo_dirty: bool | None,
    target_build: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "task_id": task.task_id,
        "leaf_id": task.leaf_id,
        "attempt": task.attempt,
        "debug_only": task.debug_only,
        "role": task.role,
        "repo_root": str(root),
        "repo_commit": repo_commit,
        "repo_dirty": repo_dirty,
        "dut": flow.name,
        "mode": "formal" if flow.kind == "fv" else "sim",
        "framework": flow.framework,
        "tool": tool,
        "executor": executor,
        "overlay": str(overlay) if overlay else None,
        "site": str(site) if site else None,
        "stage": task.stage,
        "item": task.item,
        "target": task.target,
        "seed": task.seed,
        "nest": task.nest,
        "multi_target": multi_target,
        "run_dir": str(task.run_dir),
        "leaf_dir": str(task.leaf_dir),
        "result_json": str(task.result_json),
        "completion": str(completion_path(task.run_dir, task.task_id)),
        "timeout_sec": task.timeout_sec,
        "resources": task.resources.to_dict(),
        "cli": {
            "argv": list(argv),
            "overrides": dict(task.args_overrides),
            "ui_leaf_mode": ui_leaf_mode,
            "wave_failure_time": task.wave_failure_time,
        },
        "target_build": dict(target_build) if target_build else None,
        "python": sys.executable,
        "written_at": now_iso(),
    }
    payload[DIGEST_KEY] = manifest_digest(payload)
    return payload


def write_manifest(path: Path, payload: Mapping[str, Any]) -> Path:
    write_result(path, dict(payload))
    return path


def load_manifest(path: Path) -> dict[str, Any]:
    """Read and verify a manifest: shape, schema version, and digest."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"manifest {path} must hold one JSON object")
    version = data.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            f"manifest {path}: schema_version {version!r} is not {MANIFEST_SCHEMA_VERSION}"
        )
    recorded = data.get(DIGEST_KEY)
    if recorded != manifest_digest(data):
        raise ManifestError(f"manifest {path}: {DIGEST_KEY} does not match its content")
    for key in ("task_id", "dut", "tool", "stage", "item", "seed", "run_dir", "leaf_dir", "cli"):
        if key not in data:
            raise ManifestError(f"manifest {path}: missing key `{key}`")
    overrides = data["cli"].get("overrides") or {}
    unknown = sorted(set(overrides) - OVERRIDABLE_ARGS)
    if unknown:
        raise ManifestError(f"manifest {path}: overrides not allowed: {', '.join(unknown)}")
    return data


def task_from_manifest(data: Mapping[str, Any]) -> LeafTask:
    cli = data.get("cli") or {}
    return LeafTask(
        task_id=str(data["task_id"]),
        leaf_id=int(data.get("leaf_id", 0)),
        stage=str(data["stage"]),
        item=str(data["item"]),
        seed=int(data["seed"]),
        attempt=int(data.get("attempt", 0)),
        run_dir=Path(str(data["run_dir"])),
        leaf_dir=Path(str(data["leaf_dir"])),
        target=data.get("target"),
        nest=bool(data.get("nest", False)),
        role=str(data.get("role") or LEAF_ROLE),
        debug_only=bool(data.get("debug_only", False)),
        timeout_sec=data.get("timeout_sec"),
        resources=ResourceRequest.from_mapping(data.get("resources")),
        args_overrides=dict(cli.get("overrides") or {}),
        wave_failure_time=cli.get("wave_failure_time"),
    )


def attempt_args(
    base: argparse.Namespace, task: LeafTask, *, ui_leaf_mode: str | None = None
) -> argparse.Namespace:
    """The command line one attempt runs with: the run's, plus the task's overrides."""
    args = copy.copy(base)
    for name, value in task.args_overrides.items():
        if name not in OVERRIDABLE_ARGS:
            raise ManifestError(f"attempt override not allowed: {name}")
        setattr(args, name, value)
    if ui_leaf_mode is not None:
        args._ui_leaf_mode = ui_leaf_mode
    if task.debug_only:
        args._wave_debug_rerun = True
        args._wave_failure_time = task.wave_failure_time
    return args


def execute_attempt(
    *,
    flow: Flow,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: TestCatalog,
    task: LeafTask,
    args: argparse.Namespace,
    tool: str,
    simulators: dict[str, Any],
    policies: dict[str, Any],
) -> tuple[StageResult, str | None]:
    """Run one attempt and write its leaf ``result.json``; the repo-relative path comes back.

    Outputs an earlier invocation left at the attempt's paths are removed first; a dry run
    removes nothing.
    """
    if not getattr(args, "dry_run", False):
        clear_attempt_outputs(task)
    result = run_stage(
        flow,
        root,
        sim_cfg,
        catalog,
        task.stage,
        task.item or None,
        args,
        tool,
        task.run_dir,
        simulators,
        policies,
        nest=task.nest,
        attempt=task.attempt,
        seed_override=task.seed,
    )
    result_json = repo_rel(root, task.result_json)
    if not getattr(args, "dry_run", False):
        write_result(
            task.result_json,
            fragment_payload(
                flow=flow,
                root=root,
                tool=tool,
                run_dir=task.run_dir,
                item=task.item,
                seed=task.seed,
                result=result,
            ),
        )
    return result, result_json


def write_completion(
    path: Path, task: LeafTask, result: StageResult, result_json: str | None
) -> None:
    """The worker's own record that the attempt ended, beside the manifest."""
    write_result(
        path,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "task_id": task.task_id,
            "status": result.status,
            "return_code": result.return_code,
            "result_json": result_json,
            "ended_at": result.ended_at or now_iso(),
            "worker": {"host": os.uname().nodename, "pid": os.getpid(), "python": sys.executable},
        },
    )


__all__ = [
    "DIGEST_KEY",
    "MANIFEST_SCHEMA_VERSION",
    "OVERRIDABLE_ARGS",
    "ManifestError",
    "attempt_args",
    "clear_attempt_outputs",
    "completion_path",
    "execute_attempt",
    "jobs_dir",
    "load_manifest",
    "manifest_digest",
    "manifest_path",
    "manifest_payload",
    "repo_identity",
    "task_from_manifest",
    "write_completion",
    "write_manifest",
]
