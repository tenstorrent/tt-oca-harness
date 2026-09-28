# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Combine plan for `--cov-combine`: finished coverage runs as the inputs of one new run.

The plan reads each run's `result.json` and `cov/coverage.json`, checks that the runs can be
graded as one set, and hands the merge phase the design and merged databases to combine.
The runs stay untouched; the combined run is a new run directory graded like any other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coverage import CoverageDiscovery, CoverageInput, artifact_ready, load_manifest
from .models import ConfigError, Flow
from .paths import repo_path, repo_rel
from .results import incomplete_run_note, run_is_complete


@dataclass(frozen=True)
class CombineInput:
    """One finished run selected for the combined run."""

    run_dir: Path
    result_json: Path
    framework: str
    status: str
    commit: str | None
    dirty: bool | None
    tool_version: str | None
    target: str | None
    build_fingerprint: str | None
    merged: Path
    design_db: Path | None
    leaves: int

    def payload(self, root: Path) -> dict[str, Any]:
        return {
            "run_dir": repo_rel(root, self.run_dir),
            "result_json": repo_rel(root, self.result_json),
            "framework": self.framework,
            "status": self.status,
            "commit": self.commit,
            "dirty": self.dirty,
            "tool_version": self.tool_version,
            "target": self.target,
            "build_fingerprint": self.build_fingerprint,
            "merged": repo_rel(root, self.merged),
            "design_db": repo_rel(root, self.design_db) if self.design_db else None,
            "leaves": self.leaves,
        }


@dataclass(frozen=True)
class CombinePlan:
    """The validated inputs of one combined run."""

    tool: str
    runs: list[CombineInput]

    @property
    def commit(self) -> str | None:
        return self.runs[0].commit if self.runs else None

    @property
    def target(self) -> str | None:
        targets = {run.target for run in self.runs}
        return next(iter(targets)) if len(targets) == 1 else None

    @property
    def build_fingerprint(self) -> str | None:
        fingerprints = {run.build_fingerprint for run in self.runs}
        return next(iter(fingerprints)) if len(fingerprints) == 1 else None

    @property
    def frameworks(self) -> list[str]:
        seen: list[str] = []
        for run in self.runs:
            if run.framework not in seen:
                seen.append(run.framework)
        return seen

    def input_paths(self) -> list[str]:
        """Design databases first, each once, then every run's merged database."""
        paths: list[str] = []
        for run in self.runs:
            if run.design_db is not None and str(run.design_db) not in paths:
                paths.append(str(run.design_db))
        paths.extend(str(run.merged) for run in self.runs)
        return paths

    def discovery(self, root: Path) -> CoverageDiscovery:
        return CoverageDiscovery(
            inputs=[
                CoverageInput(
                    path=repo_rel(root, run.merged) or str(run.merged),
                    item=f"run:{run.run_dir.name}",
                    seed=None,
                    attempt=0,
                    status=run.status,
                    target=run.target,
                    build_fingerprint=run.build_fingerprint,
                    result_json=repo_rel(root, run.result_json),
                    source="run_dir",
                )
                for run in self.runs
            ],
            rejected=[],
            selection_source="run_dirs",
        )

    def manifest_payload(self, root: Path) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "frameworks": self.frameworks,
            "input_runs": [run.payload(root) for run in self.runs],
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: unreadable run record ({exc})") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: run record is not a JSON object")
    return value


def _load_run(root: Path, flow: Flow, run_dir: Path) -> tuple[CombineInput, str]:
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise ConfigError(f"--cov-combine: {run_dir} has no result.json")
    result = _read_json(result_path)
    if result.get("flow") != flow.name:
        raise ConfigError(f"{result_path}: flow is `{result.get('flow')}`, expected `{flow.name}`")
    if not run_is_complete(result):
        note = incomplete_run_note(result.get("tests")) or "incomplete run"
        raise ConfigError(f"{result_path}: {note}; only finished runs merge")
    tool = result.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ConfigError(f"{result_path}: missing original tool")
    # Artifact paths in a run's records are relative to the checkout that produced the run,
    # so a run tree merged from another checkout resolves against its own root.
    run_root = root
    recorded_run_dir = result.get("run_dir")
    if isinstance(recorded_run_dir, str) and recorded_run_dir:
        suffix = Path(recorded_run_dir)
        if run_dir.parts[-len(suffix.parts) :] == suffix.parts:
            run_root = Path(*run_dir.parts[: len(run_dir.parts) - len(suffix.parts)])
    manifest_path = run_dir / "cov" / "coverage.json"
    if not manifest_path.is_file():
        raise ConfigError(f"--cov-combine: {run_dir} has no coverage manifest (cov/coverage.json)")
    manifest = load_manifest(manifest_path)
    if manifest.get("dut") != flow.name or manifest.get("tool") != tool:
        raise ConfigError(f"{manifest_path}: coverage manifest DUT/tool does not match the run")
    # The grade of an input run is immaterial: the combined run is graded on its own. What
    # it needs from each input is a merge and a report that both completed.
    if manifest.get("status") not in {"PASS", "FAIL"} or any(
        manifest.get(key) != 0 for key in ("merge_return_code", "report_return_code")
    ):
        raise ConfigError(
            f"{manifest_path}: coverage status is `{manifest.get('status')}` with merge and "
            f"report return codes {manifest.get('merge_return_code')}/"
            f"{manifest.get('report_return_code')}; a run merges after its own merge and "
            "report completed"
        )
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    merged_value = artifacts.get("merged")
    if not isinstance(merged_value, str) or not merged_value:
        raise ConfigError(f"{manifest_path}: no merged database is recorded")
    merged = repo_path(run_root, merged_value)
    if not artifact_ready(merged):
        raise ConfigError(f"{manifest_path}: merged database is missing or empty: {merged}")
    # The merged database holds the design data its own merge loaded first, so the union
    # needs the design database only where one exists.
    design_db: Path | None = None
    design_value = artifacts.get("design_db")
    if isinstance(design_value, str) and design_value:
        candidate = repo_path(run_root, design_value)
        if artifact_ready(candidate):
            design_db = candidate
    git = result.get("git") if isinstance(result.get("git"), dict) else {}
    dirty_value = git.get("dirty")
    if isinstance(dirty_value, str):
        dirty: bool | None = dirty_value.lower() == "true"
    elif isinstance(dirty_value, bool):
        dirty = dirty_value
    else:
        dirty = None
    tests = result.get("tests") if isinstance(result.get("tests"), dict) else {}
    leaves = tests.get("leaves_run", len(manifest.get("inputs", []) or []))
    return CombineInput(
        run_dir=run_dir,
        result_json=result_path,
        framework=str(result.get("framework") or ""),
        status=str(result.get("status") or "UNKNOWN"),
        commit=str(git.get("commit")) if git.get("commit") else None,
        dirty=dirty,
        tool_version=manifest.get("tool_version") or result.get("tool_version"),
        target=manifest.get("target") if isinstance(manifest.get("target"), str) else None,
        build_fingerprint=(
            manifest.get("build_fingerprint")
            if isinstance(manifest.get("build_fingerprint"), str)
            else None
        ),
        merged=merged,
        design_db=design_db,
        leaves=int(leaves) if isinstance(leaves, int) else 0,
    ), tool


def plan_combine(
    root: Path,
    flow: Flow,
    tool: str | None,
    run_dirs: list[Path],
) -> CombinePlan:
    """Validate the finished runs and return the combine plan.

    Every run must belong to the DUT, be complete, carry a passed coverage record with a
    merged database, and use one tool; a `--tool` request must name that tool. The runs must
    record one commit, since one merged figure describes one revision of the design.
    """
    if len(run_dirs) < 2:
        raise ConfigError("--cov-combine takes at least two run directories")
    resolved: list[Path] = []
    for run_dir in run_dirs:
        path = run_dir if run_dir.is_absolute() else root / run_dir
        path = path.resolve()
        if path in resolved:
            raise ConfigError(f"--cov-combine names {run_dir} twice")
        resolved.append(path)
    runs: list[CombineInput] = []
    tools: set[str] = set()
    for path in resolved:
        run, run_tool = _load_run(root, flow, path)
        runs.append(run)
        tools.add(run_tool)
    if len(tools) != 1:
        raise ConfigError(
            "--cov-combine: the runs use different tools: " + ", ".join(sorted(tools))
        )
    run_tool = next(iter(tools))
    if tool and tool != run_tool:
        raise ConfigError(f"requested tool `{tool}` does not match the runs' tool `{run_tool}`")
    commits = {run.commit for run in runs}
    if len(commits) != 1:
        listing = ", ".join(
            f"{repo_rel(root, run.run_dir)}={run.commit or 'unknown'}" for run in runs
        )
        raise ConfigError(f"--cov-combine: the runs record different commits: {listing}")
    return CombinePlan(tool=run_tool, runs=runs)
