# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Coverage collection, merge input selection, and report normalization."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC
from .models import ConfigError
from .paths import repo_rel

CANONICAL_METRICS = (
    "line",
    "cond",
    "toggle",
    "branch",
    "fsm",
    "assert",
    "functional",
    "expression",
    "user",
)

_METRIC_ALIASES = {
    "line": "line",
    "lines": "line",
    "toggle": "toggle",
    "toggles": "toggle",
    "tgl": "toggle",
    "branch": "branch",
    "branches": "branch",
    "cond": "cond",
    "condition": "cond",
    "conditions": "cond",
    "fsm": "fsm",
    "state": "fsm",
    "states": "fsm",
    "fsm_state": "fsm",
    "fsm_transition": "fsm",
    "assert": "assert",
    "assertion": "assert",
    "assertions": "assert",
    "group": "functional",
    "groups": "functional",
    "covergroup": "functional",
    "covergroups": "functional",
    "functional": "functional",
    "expr": "expression",
    "expression": "expression",
    "user": "user",
}
_OVERALL_ALIASES = {"overall", "total", "score"}
_PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%?")
_KEY_VALUE_RE = re.compile(
    r"(?im)^\s*(?P<name>line|lines|cond|condition|conditions|toggle|toggles|tgl|"
    r"branch|branches|fsm|state|states|fsm_state|fsm_transition|assert|assertion|"
    r"assertions|group|groups|covergroup|covergroups|functional|expr|expression|"
    r"user|overall|total|score)"
    r"(?:\s+coverage)?\s*(?:[:=]|\s)\s*(?P<value>\d+(?:\.\d+)?)\s*%?"
)


class CoverageError(RuntimeError):
    """Base class for coverage-stage failures."""


class CoverageCompatibilityError(CoverageError):
    """Raised when native databases cannot be safely merged."""


class CoverageReportError(CoverageError):
    """Raised when a vendor report cannot be normalized."""


@dataclass(frozen=True)
class CoverageInput:
    """One selected native coverage database and its simulation provenance."""

    path: str
    item: str | None
    seed: int | None
    attempt: int
    status: str
    target: str | None
    build_fingerprint: str | None
    result_json: str | None
    source: str


@dataclass(frozen=True)
class CoverageDiscovery:
    """Selected inputs plus inputs rejected during deterministic discovery."""

    inputs: list[CoverageInput]
    rejected: list[dict[str, Any]]
    selection_source: str


def render_tokens(
    values: list[str],
    context: dict[str, str],
    inputs: list[str] | None = None,
) -> list[str]:
    """Render a coverage argv list without invoking a shell."""

    rendered: list[str] = []
    input_paths = inputs or []
    for token in values:
        if token == "{inputs}":
            if rendered and rendered[-1] == "-dir":
                rendered.pop()
                for path in input_paths:
                    rendered.extend(["-dir", path])
                continue
            rendered.extend(input_paths)
            continue
        value = token
        for key, replacement in context.items():
            value = value.replace("{" + key + "}", replacement)
        value = value.replace("{inputs}", " ".join(input_paths))
        rendered.append(value)
    return rendered


def coverage_artifact_path(tool_cfg: dict[str, Any], cov_dir: Path) -> Path:
    """Resolve the configured per-test native coverage artifact."""

    template = tool_cfg.get("artifact")
    if not isinstance(template, str) or not template.strip():
        raise ConfigError("coverage backend is missing a non-empty `artifact` path")
    rendered = render_tokens([template], {"cov_dir": str(cov_dir)})[0]
    return Path(rendered)


def artifact_ready(path: Path) -> bool:
    """Return true only when a file/database contains usable output."""

    if path.is_file():
        try:
            return path.stat().st_size > 0
        except OSError:
            return False
    if path.is_dir():
        try:
            return any(path.iterdir())
        except OSError:
            return False
    return False


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _resolve_artifact(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _attempt_from_path(path: Path) -> int:
    for part in reversed(path.parts):
        match = re.fullmatch(r"attempt_(\d+)", part)
        if match:
            return int(match.group(1))
    return 0


def _coverage_input_from_fragment(
    *,
    root: Path,
    result_path: Path,
    data: dict[str, Any],
    flow: str,
    tool: str,
) -> tuple[CoverageInput | None, dict[str, Any] | None]:
    item = data.get("item")
    seed = data.get("seed")
    artifacts = data.get("artifacts")
    if not isinstance(item, str) or seed is None or not isinstance(artifacts, dict):
        return None, None
    coverage_value = artifacts.get("coverage")
    if not isinstance(coverage_value, str) or not coverage_value:
        return None, None
    if data.get("flow") != flow or data.get("tool") != tool:
        raise CoverageCompatibilityError(
            f"{result_path}: coverage fragment belongs to "
            f"{data.get('flow')}/{data.get('tool')}, expected {flow}/{tool}"
        )

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    coverage_meta = metadata.get("coverage") if isinstance(metadata.get("coverage"), dict) else {}
    if bool(metadata.get("debug_only") or coverage_meta.get("debug_only")):
        return None, {
            "result_json": repo_rel(root, result_path),
            "reason": "debug-only rerun",
        }

    artifact_path = _resolve_artifact(root, coverage_value)
    if not artifact_ready(artifact_path):
        return None, {
            "result_json": repo_rel(root, result_path),
            "path": repo_rel(root, artifact_path),
            "reason": "coverage artifact missing or empty",
        }

    target_build = data.get("target_build") if isinstance(data.get("target_build"), dict) else {}
    if not target_build and isinstance(metadata.get("target_build"), dict):
        target_build = metadata["target_build"]
    attempt_value = data.get("attempt", metadata.get("attempt"))
    try:
        attempt = (
            int(attempt_value) if attempt_value is not None else _attempt_from_path(result_path)
        )
    except (TypeError, ValueError):
        attempt = _attempt_from_path(result_path)
    try:
        seed_value = int(seed)
    except (TypeError, ValueError):
        seed_value = None

    return CoverageInput(
        path=repo_rel(root, artifact_path),
        item=item,
        seed=seed_value,
        attempt=attempt,
        status=str(data.get("status", "UNKNOWN")),
        target=str(data.get("target") or target_build.get("target") or "") or None,
        build_fingerprint=(
            str(target_build.get("fingerprint")) if target_build.get("fingerprint") else None
        ),
        result_json=repo_rel(root, result_path),
        source="result_json",
    ), None


def _validate_compatibility(inputs: list[CoverageInput]) -> None:
    targets = {entry.target for entry in inputs if entry.target}
    fingerprints = {entry.build_fingerprint for entry in inputs if entry.build_fingerprint}
    if len(targets) > 1:
        raise CoverageCompatibilityError(
            "coverage inputs span incompatible targets: " + ", ".join(sorted(targets))
        )
    if len(fingerprints) > 1:
        # The failure-bucket signature keeps only the start of this message, so the
        # fingerprints lead and the records that carry each one follow.
        carriers = {
            fingerprint: sorted(
                str(entry.result_json or entry.path)
                for entry in inputs
                if entry.build_fingerprint == fingerprint
            )
            for fingerprint in fingerprints
        }
        detail = "; ".join(
            f"{fingerprint}: "
            + ", ".join(paths[:3])
            + (f", {len(paths) - 3} more" if len(paths) > 3 else "")
            for fingerprint, paths in sorted(carriers.items())
        )
        raise CoverageCompatibilityError(
            "coverage inputs span incompatible build fingerprints: "
            + ", ".join(sorted(fingerprints))
            + "; "
            + detail
        )
    if inputs and any(entry.target is None for entry in inputs) and targets:
        raise CoverageCompatibilityError(
            "coverage input target provenance is incomplete; refusing a mixed-provenance merge"
        )
    if inputs and any(entry.build_fingerprint is None for entry in inputs) and fingerprints:
        raise CoverageCompatibilityError(
            "coverage build fingerprints are incomplete; refusing a mixed-provenance merge"
        )


def discover_coverage_inputs(
    *,
    root: Path,
    run_dir: Path,
    flow: str,
    tool: str,
    fallback_glob: str,
) -> CoverageDiscovery:
    """Select final non-debug leaf artifacts, falling back to a glob when no leaf records exist."""

    candidates: list[CoverageInput] = []
    rejected: list[dict[str, Any]] = []
    for result_path in sorted(run_dir.rglob("result.json")):
        if result_path == run_dir / "result.json":
            continue
        data = _load_json(result_path)
        if data is None:
            rejected.append(
                {
                    "result_json": repo_rel(root, result_path),
                    "reason": "malformed result JSON",
                }
            )
            continue
        entry, rejection = _coverage_input_from_fragment(
            root=root,
            result_path=result_path,
            data=data,
            flow=flow,
            tool=tool,
        )
        if entry is not None:
            candidates.append(entry)
        if rejection is not None:
            rejected.append(rejection)

    selected: list[CoverageInput] = []
    if candidates:
        by_leaf: dict[tuple[str | None, int | None], CoverageInput] = {}
        for entry in candidates:
            key = (entry.item, entry.seed)
            previous = by_leaf.get(key)
            if previous is None or entry.attempt > previous.attempt:
                if previous is not None:
                    rejected.append(
                        {
                            "path": previous.path,
                            "result_json": previous.result_json,
                            "reason": "superseded retry attempt",
                        }
                    )
                by_leaf[key] = entry
            else:
                rejected.append(
                    {
                        "path": entry.path,
                        "result_json": entry.result_json,
                        "reason": "superseded retry attempt",
                    }
                )
        selected = list(by_leaf.values())
        selection_source = "result_json"
    else:
        # Run directories without leaf result.json records: fall back to the glob.
        seen: set[Path] = set()
        for path in sorted(run_dir.glob(fallback_glob)):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen or not artifact_ready(path):
                continue
            seen.add(resolved)
            selected.append(
                CoverageInput(
                    path=repo_rel(root, path),
                    item=None,
                    seed=None,
                    attempt=0,
                    status="UNKNOWN",
                    target=None,
                    build_fingerprint=None,
                    result_json=None,
                    source="legacy_glob",
                )
            )
        selection_source = "legacy_glob"

    deduplicated: list[CoverageInput] = []
    seen_paths: set[Path] = set()
    for entry in sorted(selected, key=lambda value: value.path):
        path = _resolve_artifact(root, entry.path)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen_paths:
            rejected.append({"path": entry.path, "reason": "duplicate coverage input"})
            continue
        seen_paths.add(resolved)
        deduplicated.append(entry)

    _validate_compatibility(deduplicated)
    return CoverageDiscovery(
        inputs=deduplicated,
        rejected=rejected,
        selection_source=selection_source,
    )


def _percent(hit: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((100.0 * hit) / total, 4)


def _parse_lcov(path: Path) -> tuple[dict[str, float], float | None]:
    line_found = line_hit = branch_found = branch_hit = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}, None
    for line in lines:
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        try:
            value = int(raw_value.strip())
        except ValueError:
            continue
        if key == "LF":
            line_found += value
        elif key == "LH":
            line_hit += value
        elif key == "BRF":
            branch_found += value
        elif key == "BRH":
            branch_hit += value
    metrics: dict[str, float] = {}
    line_percent = _percent(line_hit, line_found)
    branch_percent = _percent(branch_hit, branch_found)
    if line_percent is not None:
        metrics["line"] = line_percent
    if branch_percent is not None:
        metrics["branch"] = branch_percent
    return metrics, line_percent


def _parse_verilator_dat(path: Path) -> tuple[dict[str, float], float | None]:
    """Parse stable type/count fields from Verilator's textual coverage database."""

    totals: dict[str, int] = {}
    hits: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}, None
    for line in lines:
        if not line.startswith("C "):
            continue
        type_match = re.search(r"\x01t\x02([^\x01]+)", line)
        count_match = re.search(r"'\s+(\d+)\s*$", line)
        if type_match is None or count_match is None:
            continue
        canonical = _metric_name(type_match.group(1))
        if canonical not in CANONICAL_METRICS:
            continue
        count = int(count_match.group(1))
        totals[canonical] = totals.get(canonical, 0) + 1
        if count > 0:
            hits[canonical] = hits.get(canonical, 0) + 1
    metrics = {
        name: value
        for name, total in totals.items()
        if (value := _percent(hits.get(name, 0), total)) is not None
    }
    overall = _percent(sum(hits.values()), sum(totals.values()))
    return metrics, overall


def _metric_name(value: str) -> str | None:
    return _METRIC_ALIASES.get(value.lower().strip())


def _parse_text_table(text: str) -> tuple[dict[str, float], float | None]:
    metrics: dict[str, float] = {}
    overall: float | None = None
    for match in _KEY_VALUE_RE.finditer(text):
        name = match.group("name").lower()
        value = float(match.group("value"))
        canonical = _metric_name(name)
        if canonical:
            metrics[canonical] = value
        elif name in _OVERALL_ALIASES:
            overall = value

    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        headers = [token.lower() for token in re.findall(r"[A-Za-z_]+", line)]
        recognized = [
            token
            for token in headers
            if _metric_name(token) is not None or token in _OVERALL_ALIASES
        ]
        if len(recognized) < 2:
            continue
        values = [float(match.group("value")) for match in _PERCENT_RE.finditer(lines[index + 1])]
        if len(values) < len(headers):
            continue
        for name, value in zip(headers, values, strict=False):
            canonical = _metric_name(name)
            if canonical:
                metrics.setdefault(canonical, value)
            elif name in _OVERALL_ALIASES and overall is None:
                overall = value
    return metrics, overall


_URG_SUMMARY_TITLE_RE = re.compile(r"(?i)^\s*total\s+coverage\s+summary\s*:?\s*$")


def parse_urg_summary_table(text: str) -> dict[str, float]:
    """Parse URG's authoritative `Total Coverage Summary` header/value table.

    Returns lowercase native column names (score, line, cond, ...) mapped to
    their percentages. Columns reported as `--` are omitted. An empty dict
    means the table was not present in `text`.
    """

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _URG_SUMMARY_TITLE_RE.match(line):
            continue
        rows = [row for row in lines[index + 1 : index + 6] if row.strip()]
        if len(rows) < 2:
            continue
        headers = [token.lower() for token in rows[0].split()]
        cells = rows[1].split()
        if not headers or len(cells) != len(headers):
            continue
        if not any(_metric_name(name) is not None or name in _OVERALL_ALIASES for name in headers):
            continue
        values: dict[str, float] = {}
        for name, cell in zip(headers, cells, strict=True):
            if cell == "--":
                continue
            try:
                values[name] = float(cell)
            except ValueError:
                values.clear()
                break
        if values:
            return values
    return {}


def _parse_urg_dashboard(report_dir: Path) -> tuple[dict[str, float], float | None]:
    if not report_dir.is_dir():
        return {}, None
    for dashboard in sorted(report_dir.rglob("dashboard.txt")):
        try:
            text = dashboard.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        table = parse_urg_summary_table(text)
        if not table:
            continue
        metrics: dict[str, float] = {}
        overall: float | None = None
        for name, value in table.items():
            canonical = _metric_name(name)
            if canonical:
                metrics[canonical] = value
            elif name in _OVERALL_ALIASES:
                overall = value
        if metrics or overall is not None:
            return metrics, overall
    return {}, None


def _report_text_files(report_dir: Path, log_path: Path | None) -> list[Path]:
    paths: list[Path] = []
    if report_dir.is_dir():
        for pattern in ("*.txt", "*.csv", "*.log"):
            paths.extend(report_dir.rglob(pattern))
    if log_path is not None and log_path.is_file():
        paths.append(log_path)
    return sorted(set(paths))


def parse_coverage_report(
    *,
    parser: str,
    report_dir: Path,
    merged: Path,
    log_path: Path | None = None,
) -> tuple[dict[str, float], float]:
    """Normalize supported vendor report output into scalar percentages."""

    metrics: dict[str, float] = {}
    overall: float | None = None
    sweep_report_text = True
    if parser == "verilator":
        parsed_metrics, parsed_overall = _parse_verilator_dat(merged)
        metrics.update(parsed_metrics)
        if parsed_overall is not None:
            overall = parsed_overall
        info_files = sorted(report_dir.rglob("*.info")) if report_dir.is_dir() else []
        for info_file in info_files:
            parsed_metrics, parsed_overall = _parse_lcov(info_file)
            for name, value in parsed_metrics.items():
                metrics.setdefault(name, value)
            if overall is None and parsed_overall is not None:
                overall = parsed_overall
    elif parser == "urg":
        # URG's dashboard summary is the one table whose columns are pure
        # percentages; the other report files interleave raw covered/total
        # counts that the generic table sweep misreads as percentages.
        parsed_metrics, parsed_overall = _parse_urg_dashboard(report_dir)
        if parsed_metrics or parsed_overall is not None:
            metrics.update(parsed_metrics)
            overall = parsed_overall
            sweep_report_text = False

    if sweep_report_text:
        for path in _report_text_files(report_dir, log_path):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parsed_metrics, parsed_overall = _parse_text_table(text)
            for name, value in parsed_metrics.items():
                metrics.setdefault(name, value)
            if overall is None and parsed_overall is not None:
                overall = parsed_overall

    if overall is None and len(metrics) == 1:
        overall = next(iter(metrics.values()))
    if not metrics or overall is None:
        raise CoverageReportError(
            f"{parser} report did not contain a usable overall percentage and metric breakdown "
            f"(report={report_dir}, merged={merged})"
        )
    invalid = {name: value for name, value in metrics.items() if value < 0.0 or value > 100.0}
    if overall < 0.0 or overall > 100.0 or invalid:
        raise CoverageReportError("coverage report contains percentages outside 0..100")
    return {
        name: round(value, 4) for name, value in metrics.items() if name in CANONICAL_METRICS
    }, round(overall, 4)


def json_text(payload: dict[str, Any]) -> str:
    """The exact bytes `write_json` puts on disk for `payload`."""

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_json_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_text(path, json_text(payload))


def load_manifest(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if data is None:
        raise CoverageError(f"coverage manifest is missing or malformed: {path}")
    return data


def discovery_payload(discovery: CoverageDiscovery) -> dict[str, Any]:
    return {
        "selection_policy": "final_non_debug_attempt_per_test_seed",
        "selection_source": discovery.selection_source,
        "inputs": [asdict(entry) for entry in discovery.inputs],
        "rejected": discovery.rejected,
    }


def new_manifest(
    *,
    flow: str,
    tool: str,
    parser: str,
    supported_metrics: list[str],
    discovery: CoverageDiscovery,
    merged: Path,
    root: Path,
    exclude_files: list[str],
) -> dict[str, Any]:
    first = discovery.inputs[0] if discovery.inputs else None
    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "dut": flow,
        "tool": tool,
        "parser": parser,
        "status": "PENDING",
        "supported_metrics": supported_metrics,
        "target": first.target if first else None,
        "build_fingerprint": first.build_fingerprint if first else None,
        **discovery_payload(discovery),
        "exclusions": exclude_files,
        # The coverage.json key set is fixed; no config key feeds "waivers".
        "waivers": [],
        "artifacts": {
            "merged": repo_rel(root, merged),
            "report": None,
            "summary": None,
        },
    }
