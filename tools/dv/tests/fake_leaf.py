# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""A leaf stand-in for the cluster executor tests: the files a worker leaves, nothing else.

Invoked as the job script's command with the manifest path, it reads ``task_id``,
``leaf_dir``, ``completion``, ``item``, ``seed`` and ``attempt`` from the manifest, writes the
leaf's ``result.json`` and the completion record, and exits with the status code of the
verdict ``FAKE_LEAF_STATUS`` names (``PASS`` by default). ``FAKE_LEAF_SKIP_RESULT=1`` exits
without writing anything, as a worker killed mid-flight would.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

EXIT_CODES = {"PASS": 0, "FAIL": 1, "ERROR": 2, "TIMEOUT": 124, "UNKNOWN": 5}


def main(argv: list[str]) -> int:
    manifest = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    status = os.environ.get("FAKE_LEAF_STATUS", "PASS")
    code = EXIT_CODES.get(status, 2)
    if os.environ.get("FAKE_LEAF_SKIP_RESULT") == "1":
        return code
    stamp = datetime.now(UTC).isoformat()
    leaf_dir = Path(manifest["leaf_dir"])
    leaf_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "item": manifest["item"],
        "seed": manifest["seed"],
        "status": status,
        "exit_code": code,
        "return_code": code,
        "reason": "" if status == "PASS" else f"fake leaf graded {status}",
        "duration_sec": 0.25,
        "started_at": stamp,
        "ended_at": stamp,
        "log": None,
        "artifacts": {},
        "failure_buckets": [],
        "parser": None,
        "metadata": {"seed": manifest["seed"], "attempt": manifest.get("attempt", 0)},
        "attempt": manifest.get("attempt", 0),
    }
    (leaf_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    completion = Path(manifest["completion"])
    completion.parent.mkdir(parents=True, exist_ok=True)
    completion.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": manifest["task_id"],
                "status": status,
                "return_code": code,
                "result_json": str(leaf_dir / "result.json"),
                "ended_at": stamp,
            }
        ),
        encoding="utf-8",
    )
    print(f"fake leaf {manifest['task_id']} {status} job={os.environ.get('FAKE_JOB_ID', '?')}")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
