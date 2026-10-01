# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Data models and shared exceptions for the native DV runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised for invalid checked-in or CLI configuration."""


class StageTimeoutError(RuntimeError):
    """Raised when a stage exceeds its resolved timeout_sec and was killed."""


@dataclass
class Dut:
    """A resolved device-under-test config.

    Built from the per-DUT ``<dut>_sim_cfg.toml`` (merged with its shared ``profile``) and
    selected by ``--dut`` via ``hw/common/dv/configs/duts.toml`` or the directory convention.
    ``name`` is the bare DUT name (e.g. ``smc``); ``root`` is the repo-relative DUT DV root
    (e.g. ``hw/sys/smc/dv``); ``path`` points at the merged sim_cfg file; ``raw`` holds
    the merged config dict.
    """

    name: str
    kind: str
    description: str
    framework: str
    visibility: str
    runnability: str
    license: str
    root: str
    default_tool: str
    tools: list[str]
    path: Path
    raw: dict[str, Any]
    # Frameworks this DUT implements: the declared `[frameworks.<fw>]` tables in its sim config
    # (`framework` above is the selected one). Single-framework configs get a one-item list.
    frameworks: list[str] = field(default_factory=list)
    # The framework selected when no --framework is given; bare-string testlist `module` values
    # bind this framework only.
    default_framework: str = ""


# Alias: the runner and dashboard import and annotate a Dut as `Flow`.
Flow = Dut


@dataclass
class TestEntry:
    name: str
    # The entry point for the selected framework. Resolved from `bindings` at catalog load;
    # empty when the scenario has no binding for the selected framework. `excluded` tells a
    # declared-out-of-scope framework apart from a missing entry.
    module: str
    target: str | None = None
    seed: int | None = None
    reseed: int | None = None
    timeout_sec: int | None = None
    tags: list[str] | None = None
    run_modes: list[str] | None = None
    # Simulators this scenario can run on. Empty means every tool the DUT declares, which
    # is the normal case and what an absent key yields. A scenario whose stimulus depends
    # on one tool's hierarchy access -- a VPI reach into a generate block that only one
    # simulator makes public, say -- names that tool here, so selection drops it under the
    # others instead of erroring at run time. Validated against the DUT's own `tools` list
    # at catalog load.
    tools: list[str] | None = None
    args: list[str] | None = None
    firmware: str | dict[str, Any] | None = None
    # `expect_fail = "<reason>"`: the leaf reproduces a filed defect and FAILS on a DUT that still
    # carries it. The runner grades that FAIL as PASS and an observed PASS as FAIL, so the
    # reproducer runs inside a green regression and turns red the day the defect is gone.
    expect_fail: str | None = None
    # `expect_fail_match = "<regex>"`: the observed failure message must match it, so a leaf
    # that fails for a different reason than the recorded one is graded FAIL, not PASS.
    expect_fail_match: str | None = None
    # Per-framework entry points from a `module = { cocotb = "...", uvm = "..." }` binding map.
    # A bare-string `module` is normalized to a single binding for the DUT's default framework.
    bindings: dict[str, str] = field(default_factory=dict)
    # Frameworks the binding map declares out of scope with `<fw> = false`. Selection treats
    # such a framework like one the map omits (skipped from groups and tags, an error when
    # named with --items); `--list` counts the two apart.
    excluded: frozenset[str] = frozenset()
    # Per-framework runtime overrides from `[tests.overrides.<fw>]` (seed/timeout_sec/args).
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # The testlist file that declared this entry, so cross-reference errors (for example an
    # unknown run mode) name the file to edit rather than the include root.
    source: Path | None = None


@dataclass
class TestCatalog:
    path: Path | None
    tests: dict[str, TestEntry]
    groups: dict[str, list[str]]


@dataclass
class StageResult:
    stage: str
    item: str | None
    status: str
    return_code: int
    duration_sec: float
    started_at: str
    ended_at: str
    log: str | None = None
    artifacts: dict[str, Any] | None = None
    failure_buckets: list[dict[str, Any]] | None = None
    reason: str = ""
    parser: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    target: str | None = None
    # Proof totals and per-task statuses of a graded formal stage; None on every other stage.
    formal: dict[str, Any] | None = None
    # Repo-relative path of the leaf's own result.json; None on a run-level stage.
    result_json: str | None = None


@dataclass
class ParserDecision:
    status: str
    reason: str
    evidence: list[dict[str, str]]
    failure_buckets: list[dict[str, Any]]
    parser: dict[str, Any]
