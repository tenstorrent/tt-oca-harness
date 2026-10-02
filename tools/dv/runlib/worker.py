# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The worker entry point: one leaf attempt from one manifest.

``run_dv.py --worker-manifest <manifest>`` lands here on a farm machine. The worker verifies
the manifest, the checkout it names, and any build marker it names, reloads the DUT and
registries from the tree, runs exactly one ``run_stage``, writes the leaf's ``result.json`` and
a completion record, and exits with the status code the coordinator's own leaf would have. It
never provisions an environment or writes outside the leaf and jobs directories: the
coordinator is the single writer of everything else in the run tree.

Exit status 2 is an environment error, written into the leaf's ``result.json`` when the leaf
directory is known, so the coordinator grades it as such rather than as a test failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from .executors.base import LeafTask, error_result, now_iso
from .executors.manifest import (
    ManifestError,
    attempt_args,
    execute_attempt,
    load_manifest,
    repo_identity,
    task_from_manifest,
    write_completion,
)
from .models import ConfigError, StageResult
from .paths import repo_rel
from .results import exit_code_for_status, fragment_payload, write_result

ENVIRONMENT_ERROR_EXIT = 2


class WorkerError(RuntimeError):
    """The attempt cannot run on this machine; the reason is graded ``environment_error``."""


def _say(message: str) -> None:
    print(f"worker  : {message}", flush=True)


def verify_checkout(data: dict[str, Any]) -> Path:
    root = Path(str(data["repo_root"]))
    if not (root / "Bender.yml").is_file() or not (root / "pyproject.toml").is_file():
        raise WorkerError(f"repo_root is not a repository root here: {root}")
    expected = data.get("repo_commit")
    if expected:
        actual, _dirty = repo_identity(root)
        if actual is not None and actual != expected:
            raise WorkerError(
                f"checkout is at {actual[:12]}, manifest was planned at {expected[:12]}"
            )
    return root


def verify_run_tree(data: dict[str, Any]) -> None:
    run_dir = Path(str(data["run_dir"]))
    if not run_dir.is_dir():
        raise WorkerError(f"run directory is not visible here: {run_dir}")
    build = data.get("target_build") or {}
    marker = build.get("ready_marker")
    if marker and not Path(str(marker)).is_file():
        raise WorkerError(f"build ready marker is missing: {marker}")


def write_error(task: LeafTask, reason: str, *, flow: Any, root: Path, tool: str) -> None:
    result = error_result(task, reason)
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


def run_manifest(path: Path) -> int:
    """Run the attempt one manifest describes; the return value is the process exit status."""
    # The coordinator's modules import the worker's helpers, so they load here, not at import.
    from .cli import load_registries, parse_args, validate_flow
    from .config import (
        activate_adopter_overlay_env,
        load_sim_cfg,
        load_test_catalog,
        merge_simulator_defaults,
        targeted_sim_cfg,
    )
    from .duts import resolve_dut

    data = load_manifest(path)
    task = task_from_manifest(data)
    _say(
        f"manifest {path} task={task.task_id} "
        + (f"build target={task.target}" if task.is_build else f"item={task.item} seed={task.seed}")
    )
    root = verify_checkout(data)
    verify_run_tree(data)

    os.environ["OCH_ROOT"] = str(root)
    site = data.get("site")
    if site:
        os.environ["OCAH_DV_SITE"] = str(site)
    registries = load_registries(root)
    overlay = Path(str(data["overlay"])) if data.get("overlay") else None
    flow = resolve_dut(
        root,
        str(data["dut"]),
        mode=str(data.get("mode", "sim")),
        framework=data.get("framework"),
        adopter_overlay=overlay,
        site=registries.site,
    )
    tool = str(data["tool"])
    validate_flow(flow, root, registries.simulators, registries.policies, registries.executors)
    activate_adopter_overlay_env(flow.raw)
    sim_cfg = merge_simulator_defaults(load_sim_cfg(flow, root), registries.simulators, flow.tools)
    catalog = load_test_catalog(flow, root)
    if not task.is_build and task.item not in catalog.tests:
        raise WorkerError(f"test `{task.item}` is not in the catalog of DUT `{flow.name}`")
    target = task.target or None
    multi_target = bool(data.get("multi_target", False))
    if target:
        sim_cfg = targeted_sim_cfg(sim_cfg, target, force_target_filelist=multi_target)

    cli = data.get("cli") or {}
    args = parse_args(list(cli.get("argv") or []))
    args = attempt_args(args, task, ui_leaf_mode=str(cli.get("ui_leaf_mode") or "full"))
    args._multi_target_run = multi_target
    args._site_layer = registries.site.label if registries.site is not None else None
    if task.is_build:
        # The job's core request bounds the compile; without one the host's core count does.
        if task.resources.cores:
            args.build_jobs = int(task.resources.cores)
        else:
            args._cluster_executor = True
    elif target:
        # The coordinator built the model before submitting; a worker never rebuilds it.
        args._cocotb_prebuilt_targets = {target}

    try:
        result, result_json = execute_attempt(
            flow=flow,
            root=root,
            sim_cfg=sim_cfg,
            catalog=catalog,
            task=task,
            args=args,
            tool=tool,
            simulators=registries.simulators,
            policies=registries.policies,
        )
    except Exception as exc:  # noqa: BLE001
        reason = f"environment_error: attempt raised {type(exc).__name__}: {exc}"
        write_error(task, reason, flow=flow, root=root, tool=tool)
        _say(reason)
        return ENVIRONMENT_ERROR_EXIT
    completion = Path(str(data.get("completion") or (task.leaf_dir / "completion.json")))
    write_completion(completion, task, result, result_json)
    _say(f"done status={result.status} result={result_json}")
    return exit_code_for_status(result.status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_dv.py --worker-manifest",
        description="Run the one leaf attempt a manifest describes.",
    )
    parser.add_argument("manifest", help="Leaf manifest the coordinator wrote")
    ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
    path = Path(ns.manifest).expanduser().resolve()
    started = now_iso()
    try:
        return run_manifest(path)
    except (ManifestError, WorkerError, ConfigError) as exc:
        print(f"ERROR: worker: {exc}", file=sys.stderr, flush=True)
        _record_environment_error(path, str(exc), started)
        return ENVIRONMENT_ERROR_EXIT
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return ENVIRONMENT_ERROR_EXIT


def _record_environment_error(path: Path, reason: str, started_at: str) -> None:
    """Leave an ``ERROR`` leaf result when the manifest was readable enough to name the leaf."""
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        leaf_dir = Path(str(data["leaf_dir"]))
        run_dir = Path(str(data["run_dir"]))
        root = Path(str(data.get("repo_root") or run_dir))
        if not run_dir.is_dir():
            return
        result = StageResult(
            stage=str(data.get("stage", "sim")),
            item=str(data.get("item", "")),
            status="ERROR",
            return_code=ENVIRONMENT_ERROR_EXIT,
            duration_sec=0.0,
            started_at=started_at,
            ended_at=now_iso(),
            reason=f"environment_error: {reason}",
            metadata={"seed": data.get("seed"), "attempt": data.get("attempt", 0)},
        )
        payload = {
            "schema_version": 1,
            "flow": data.get("dut"),
            "tool": data.get("tool"),
            "item": result.item,
            "seed": data.get("seed"),
            "status": result.status,
            "exit_code": exit_code_for_status(result.status),
            "return_code": result.return_code,
            "reason": result.reason,
            "run_dir": repo_rel(root, run_dir),
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "duration_sec": 0.0,
            "log": None,
            "artifacts": {},
            "failure_buckets": [
                {"kind": "environment_error", "signature": result.reason[:120], "count": 1}
            ],
            "parser": None,
            "metadata": result.metadata,
            "attempt": data.get("attempt", 0),
        }
        write_result(leaf_dir / "result.json", payload)
    except Exception:  # noqa: BLE001
        return


__all__ = ["ENVIRONMENT_ERROR_EXIT", "WorkerError", "main", "run_manifest"]
