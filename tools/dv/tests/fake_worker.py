# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The real worker with a scripted stage, for the coordinator tests against a fake scheduler.

``fake_worker.py <manifest>`` runs ``runlib.worker.main`` exactly as ``run_dv.py
--worker-manifest`` would, with a scripted ``run_stage`` that returns the verdict
``FAKE_WORKER_STATUS`` scripts for the item: a JSON object mapping an item name to a status, or
to a list of statuses indexed by attempt. A target build (a manifest with no item) reads the
``build`` key, or ``build@<target>`` for one target, and answers with the ``target_build``
metadata a real build stage records. Everything else the worker does, from the digest and
checkout checks through the catalog lookup to the completion record, is the production path.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import worker  # noqa: E402
from runlib.config import default_target_name  # noqa: E402
from runlib.models import StageResult  # noqa: E402

EXIT_CODES = {"PASS": 0, "FAIL": 1, "ERROR": 2, "TIMEOUT": 124, "UNKNOWN": 5}


def scripted_status(item: str, attempt: int) -> str:
    table = json.loads(os.environ.get("FAKE_WORKER_STATUS", "{}"))
    value = table.get(item, "PASS")
    if "@" in item and item not in table:
        value = table.get(item.split("@")[0], "PASS")
    if isinstance(value, list):
        return str(value[min(attempt, len(value) - 1)]) if value else "PASS"
    return str(value)


def fake_run_stage(
    flow: Any,
    root: Path,
    sim_cfg: dict[str, Any],
    catalog: Any,
    stage: str,
    item: str | None,
    args: Any,
    tool: str,
    run_dir: Path,
    simulators: dict[str, Any],
    policies: dict[str, Any],
    *,
    nest: bool = False,
    attempt: int = 0,
    seed_override: int | None = None,
) -> StageResult:
    target = default_target_name(sim_cfg)
    if item is None:
        status = scripted_status(f"build@{target}", attempt)
        stamp = datetime.now(UTC).isoformat()
        build_dir = run_dir / "stages" / stage / target / tool
        return StageResult(
            stage=stage,
            item=None,
            status=status,
            return_code=EXIT_CODES.get(status, 2),
            duration_sec=0.5,
            started_at=stamp,
            ended_at=stamp,
            log=None,
            artifacts={},
            failure_buckets=[],
            reason="" if status == "PASS" else f"scripted build {status}",
            metadata={
                "target": target,
                "fake_worker": True,
                "build_jobs": getattr(args, "build_jobs", None),
                "target_build": {
                    "target": target,
                    "tool": tool,
                    "build_dir": str(build_dir),
                    "artifact": str(build_dir),
                    "executor": "fake",
                    "status": status,
                },
            },
            target=target,
        )
    status = scripted_status(str(item), attempt)
    stamp = datetime.now(UTC).isoformat()
    return StageResult(
        stage=stage,
        item=item,
        status=status,
        return_code=EXIT_CODES.get(status, 2),
        duration_sec=0.5,
        started_at=stamp,
        ended_at=stamp,
        log=None,
        artifacts={},
        failure_buckets=[],
        reason="" if status == "PASS" else f"scripted {status}",
        parser={"name": "fake"},
        metadata={"seed": seed_override, "attempt": attempt, "fake_worker": True},
        target=getattr(args, "target", None),
    )


def main(argv: list[str]) -> int:
    with mock.patch("runlib.executors.manifest.run_stage", fake_run_stage):
        return int(worker.main(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
