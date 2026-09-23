# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Publish static dashboard artifacts with timestamped history and latest copy."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "0.1"


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _is_remote(path: str) -> bool:
    return path.startswith(("gs://", "s3://"))


def _join_remote(root: str, *parts: str) -> str:
    return "/".join([root.rstrip("/"), *(part.strip("/") for part in parts)])


# Publish destinations are limited to gs:// or s3:// bucket/key paths built from
# characters this flow actually produces; anything else (flag-like tokens,
# whitespace, shell metacharacters, dot-only segments) is rejected before
# reaching gsutil/aws.
_REMOTE_DESTINATION_RE = re.compile(r"^(?:gs|s3)://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def _sync_remote(source: Path, destination: str) -> None:
    if not _REMOTE_DESTINATION_RE.fullmatch(destination) or {".", ".."} & set(
        destination.split("/")
    ):
        raise ValueError(f"unsupported or unsafe remote publish path: {destination}")
    if destination.startswith("gs://"):
        cmd = ["gsutil", "-m", "rsync", "-r", "-d", str(source), destination]
    else:
        cmd = ["aws", "s3", "sync", "--delete", str(source), destination]
    subprocess.run(cmd, check=True)


def _source_files(source: Path) -> list[str]:
    return sorted(str(path.relative_to(source)) for path in source.rglob("*") if path.is_file())


def _summary_result_files(source: Path) -> list[str]:
    summary = source / "summary.json"
    if not summary.is_file():
        return []
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    result_files: list[str] = []
    for result in data.get("results") or []:
        if not isinstance(result, dict):
            continue
        artifacts = result.get("artifacts", {})
        if isinstance(artifacts, dict) and artifacts.get("result_json"):
            result_files.append(str(artifacts["result_json"]))
    return sorted(dict.fromkeys(result_files))


def write_manifest(source: Path, name: str, timestamp: str) -> Path:
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "publish_name": name,
        "timestamp": timestamp,
        "source": str(source),
        "source_result_files": _summary_result_files(source),
        "output_files": _source_files(source),
    }
    path = source / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def publish_local(
    source: Path,
    publish_root: Path,
    name: str,
    timestamp: str | None = None,
) -> tuple[str, str]:
    """Copy a generated report directory into local history and latest paths."""
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")

    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    write_manifest(source, name, ts)
    history_dir = publish_root / name / ts
    latest_dir = publish_root / name / "latest"
    history_dir.parent.mkdir(parents=True, exist_ok=True)

    _copy_tree(source, history_dir)
    _copy_tree(source, latest_dir)
    return str(history_dir), str(latest_dir)


def publish_remote(
    source: Path,
    publish_root: str,
    name: str,
    timestamp: str | None = None,
) -> tuple[str, str]:
    """Sync a generated report directory to object storage history and latest paths."""
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")

    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    write_manifest(source, name, ts)
    history_dir = _join_remote(publish_root, name, ts)
    latest_dir = _join_remote(publish_root, name, "latest")
    _sync_remote(source, history_dir)
    _sync_remote(source, latest_dir)
    return history_dir, latest_dir


def publish(
    source: Path, publish_root: str, name: str, timestamp: str | None = None
) -> tuple[str, str]:
    """Copy a generated report directory into timestamped and latest locations."""
    if _is_remote(publish_root):
        return publish_remote(source, publish_root, name, timestamp)
    return publish_local(source, Path(publish_root).expanduser().resolve(), name, timestamp)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="generated report directory")
    parser.add_argument("--publish-root", required=True, help="publish root directory")
    parser.add_argument("--name", default="dashboard", help="published artifact name")
    parser.add_argument("--timestamp", help="override timestamp for reproducible tests")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        history_dir, latest_dir = publish(
            Path(args.source).resolve(),
            args.publish_root,
            args.name,
            args.timestamp,
        )
        print(f"Published history: {history_dir}")
        print(f"Published latest : {latest_dir}")
        return 0
    except (OSError, ValueError, shutil.Error, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
