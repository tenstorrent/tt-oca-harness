"""Data models and shared exceptions for the native DV runner."""

from __future__ import annotations

from dataclasses import dataclass
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
    (e.g. ``dv/oss/hw/sys/smc/dv``); ``path`` points at the merged sim_cfg file; ``raw`` holds
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


# Back-compat alias: much of the runner/dashboard still annotates and imports `Flow`. The concept
# is now a DUT; keeping the alias avoids churning ~150 call sites for no functional change.
Flow = Dut


@dataclass
class TestEntry:
    name: str
    module: str
    target: str | None = None
    seed: int | None = None
    reseed: int | None = None
    timeout_sec: int | None = None
    tags: list[str] | None = None
    run_modes: list[str] | None = None
    args: list[str] | None = None
    firmware: str | dict[str, Any] | None = None


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


@dataclass
class ParserDecision:
    status: str
    reason: str
    evidence: list[dict[str, str]]
    failure_buckets: list[dict[str, Any]]
    parser: dict[str, Any]
