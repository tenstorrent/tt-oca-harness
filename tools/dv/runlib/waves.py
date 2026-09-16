# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Waveform option resolution, ranged capture metadata, and retention helpers."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from .config import as_str_list
from .models import ConfigError
from .paths import repo_rel

WAVE_DEFAULT = "default"
NON_PASS_STATUSES = {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
TIME_UNITS_PS = {
    "fs": 0.001,
    "ps": 1,
    "ns": 1_000,
    "us": 1_000_000,
    "ms": 1_000_000_000,
    "s": 1_000_000_000_000,
}
TIME_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:time\s*[=:]\s*)?(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>fs|ps|ns|us|ms|s)\b",
    re.IGNORECASE,
)


def _append_repeat_option(command: list[str], flag: str, values: list[str] | None) -> None:
    for value in values or []:
        command.extend([flag, str(value)])


def waves_requested(args: Any) -> bool:
    return bool(getattr(args, "waves", None))


def waves_on_fail_requested(args: Any) -> bool:
    return bool(getattr(args, "waves_on_fail", None))


def wave_active(args: Any) -> bool:
    return waves_requested(args) or bool(getattr(args, "_wave_debug_rerun", False))


def parse_time_ps(value: str | None, option: str) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower().replace("_", "")
    match = re.fullmatch(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>fs|ps|ns|us|ms|s)", text)
    if not match:
        raise ConfigError(f"{option} must be a time with units fs|ps|ns|us|ms|s, got `{value}`")
    number = float(match.group("value"))
    ps = number * TIME_UNITS_PS[match.group("unit")]
    return max(0, int(round(ps)))


def format_time_ps(ps: int | None) -> str | None:
    if ps is None:
        return None
    for unit, scale in (
        ("s", TIME_UNITS_PS["s"]),
        ("ms", TIME_UNITS_PS["ms"]),
        ("us", TIME_UNITS_PS["us"]),
        ("ns", TIME_UNITS_PS["ns"]),
        ("ps", 1),
    ):
        if ps >= scale and ps % int(scale) == 0:
            return f"{ps // int(scale)}{unit}"
    return f"{ps}ps"


def find_failure_time_ps(log_path: Path | None) -> dict[str, Any]:
    if log_path is None or not log_path.is_file():
        return {"time_ps": None, "source": "not_found"}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"time_ps": None, "source": "unreadable"}
    matches: list[dict[str, Any]] = []
    for match in TIME_RE.finditer(text):
        value = match.group("value")
        unit = match.group("unit").lower()
        time_ps = int(round(float(value) * TIME_UNITS_PS[unit]))
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end].strip()
        severity_score = 1
        if re.search(r"fail|fatal|error|assert|timeout", line, re.IGNORECASE):
            severity_score = 0
        matches.append(
            {
                "time_ps": time_ps,
                "raw": match.group(0).strip(),
                "line": line[:240],
                "severity_score": severity_score,
            }
        )
    if not matches:
        return {"time_ps": None, "source": "not_found"}
    matches.sort(key=lambda item: (item["severity_score"], item["time_ps"]))
    chosen = matches[0]
    return {
        "time_ps": chosen["time_ps"],
        "source": "log_timestamp",
        "raw": chosen["raw"],
        "line": chosen["line"],
    }


# simv dlopens <VERDI_HOME>/<subdir>/libnovas.so for UCLI `dump -type FSDB`; the platform
# directory name differs across Verdi releases.
NOVAS_PLI_SUBDIRS = ("share/PLI/VCS/LINUXAMD64", "share/PLI/VCS/LINUX64")


def _has_novas_pli(home: Path) -> bool:
    return any((home / sub / "libnovas.so").is_file() for sub in NOVAS_PLI_SUBDIRS)


def verdi_home_candidates() -> list[Path]:
    """Possible Verdi roots: $VERDI_HOME, then the install root above `verdi` on PATH."""
    candidates: list[Path] = []
    explicit = os.environ.get("VERDI_HOME", "").strip()
    if explicit:
        candidates.append(Path(explicit))
    verdi = shutil.which("verdi")
    if verdi:
        derived = Path(verdi).resolve().parents[1]
        if derived not in candidates:
            candidates.append(derived)
    return candidates


def resolve_verdi_home() -> str | None:
    """First candidate Verdi root that actually ships the Novas FSDB writer."""
    for home in verdi_home_candidates():
        if _has_novas_pli(home):
            return str(home)
    return None


def require_verdi_home(tool: str, wave_format: str) -> str | None:
    """FSDB dumping on VCS loads Verdi's FSDB writer through VERDI_HOME; fail fast when absent."""
    if tool != "vcs" or wave_format != "fsdb":
        return None
    home = resolve_verdi_home()
    if home is None:
        candidates = verdi_home_candidates()
        checked = (
            "; ".join(
                f"`{c}` (missing <home>/{{{'|'.join(NOVAS_PLI_SUBDIRS)}}}/libnovas.so)"
                for c in candidates
            )
            if candidates
            else "VERDI_HOME is unset and `verdi` is not on PATH"
        )
        raise ConfigError(
            "waveform format `fsdb` on VCS needs Verdi's FSDB writer (libnovas.so). "
            f"Checked: {checked}. Set VERDI_HOME to a Verdi installation root, or use "
            "`--waves vpd` which needs no Verdi installation"
        )
    return home


def _tool_wave_cfg(simulators: dict[str, Any], tool: str) -> dict[str, Any]:
    cfg = simulators.get(tool, {})
    if not isinstance(cfg, dict):
        raise ConfigError(f"tool `{tool}` missing from simulator registry")
    return cfg


def resolve_wave_format(
    args: Any, simulators: dict[str, Any], tool: str, *, on_fail: bool = False
) -> str:
    request = getattr(args, "waves_on_fail", None) if on_fail else getattr(args, "waves", None)
    if request is None and bool(getattr(args, "_wave_debug_rerun", False)):
        request = getattr(args, "waves", None)
    if not request:
        return ""
    request_text = str(request).strip().lower()
    cfg = _tool_wave_cfg(simulators, tool)
    supported = [
        fmt.lower() for fmt in as_str_list(cfg.get("supports_waves"), f"{tool}.supports_waves")
    ]
    default = str(cfg.get("default_waves") or "").strip().lower()
    if request_text == WAVE_DEFAULT:
        request_text = default
    if not request_text:
        raise ConfigError(f"tool `{tool}` has no default waveform format")
    if request_text not in supported:
        raise ConfigError(
            f"tool `{tool}` does not support waveform format `{request_text}`; "
            f"supported: {', '.join(supported) if supported else 'none'}"
        )
    return request_text


def wave_time_range(args: Any, *, failure_time_ps: int | None = None) -> dict[str, Any]:
    start_ps = parse_time_ps(getattr(args, "wave_start", None), "--wave-start")
    end_ps = parse_time_ps(getattr(args, "wave_end", None), "--wave-end")
    window_ps = parse_time_ps(getattr(args, "wave_window", None), "--wave-window")
    margin_ps = parse_time_ps(getattr(args, "wave_margin", None), "--wave-margin")
    if margin_ps is None and window_ps is not None:
        margin_ps = parse_time_ps("10us", "--wave-margin")

    source = "none"
    if start_ps is not None or end_ps is not None:
        source = "explicit"
    elif failure_time_ps is not None and window_ps is not None:
        start_ps = max(0, failure_time_ps - window_ps)
        end_ps = failure_time_ps + (margin_ps or 0)
        source = "failure_time_minus_window"
    elif window_ps is not None:
        source = "window_requested_without_failure_time"

    if start_ps is not None and end_ps is not None and end_ps <= start_ps:
        raise ConfigError("--wave-end must be greater than --wave-start")

    return {
        "start_ps": start_ps,
        "end_ps": end_ps,
        "window_ps": window_ps,
        "margin_ps": margin_ps,
        "failure_time_ps": failure_time_ps,
        "source": source,
    }


def wave_range_metadata(range_info: dict[str, Any]) -> dict[str, Any] | None:
    if range_info.get("source") == "none":
        return None
    return {
        "start": format_time_ps(range_info.get("start_ps")),
        "end": format_time_ps(range_info.get("end_ps")),
        "source": range_info.get("source"),
        "failure_time": format_time_ps(range_info.get("failure_time_ps")),
        "window": format_time_ps(range_info.get("window_ps")),
        "margin": format_time_ps(range_info.get("margin_ps")),
    }


def expected_wave_paths(waves_dir: Path, item: str, tool: str, wave_format: str) -> list[Path]:
    if not wave_format:
        return []
    if tool == "xcelium" and wave_format == "shm":
        return [waves_dir / f"{item}.shm"]
    suffix = {
        "fst": ".fst",
        "vcd": ".vcd",
        "vpd": ".vpd",
        "fsdb": ".fsdb",
        "shm": ".shm",
    }.get(wave_format, f".{wave_format}")
    return [waves_dir / f"{item}{suffix}"]


def discovered_wave_paths(waves_dir: Path, item: str, tool: str, wave_format: str) -> list[Path]:
    expected = expected_wave_paths(waves_dir, item, tool, wave_format)
    paths = [path for path in expected if path.exists()]
    if waves_dir.is_dir():
        for path in sorted(waves_dir.glob("*")):
            if path not in paths:
                paths.append(path)
    return paths or expected


def actual_wave_paths(waves_dir: Path, item: str, tool: str, wave_format: str) -> list[Path]:
    expected = expected_wave_paths(waves_dir, item, tool, wave_format)
    paths = [path for path in expected if path.exists()]
    if waves_dir.is_dir():
        for path in sorted(waves_dir.glob("*")):
            if (
                path.is_file()
                and path.suffix.lstrip(".").lower() == wave_format
                and path not in paths
            ):
                paths.append(path)
            elif (
                wave_format == "shm"
                and path.is_dir()
                and path.suffix.lower() == ".shm"
                and path not in paths
            ):
                paths.append(path)
    return paths


def viewer_commands(wave_files: list[str], wave_format: str) -> list[str]:
    commands: list[str] = []
    for wave_file in wave_files:
        quoted = shlex.quote(wave_file)
        if wave_format in {"fst", "vcd"}:
            commands.append(f"gtkwave {quoted}")
        elif wave_format == "fsdb":
            commands.append(f"verdi -ssf {quoted}")
        elif wave_format == "vpd":
            commands.append(f"dve -vpd {quoted}")
        elif wave_format == "shm":
            commands.append(f"simvision {quoted}")
        else:
            commands.append(
                f"# Open {quoted} with a viewer that supports {shlex.quote(wave_format)}"
            )
    return commands


def same_seed_replay_command(
    *,
    flow_name: str,
    item: str,
    seed: int,
    tool: str,
    wave_format: str,
    args: Any,
) -> str:
    command = [
        "python3",
        "tools/dv/run_dv.py",
        "--dut",
        flow_name,
        "--items",
        item,
        "--stage",
        "sim",
        "--tool",
        tool,
        "--seed",
        str(seed),
        "--waves",
        wave_format,
    ]
    if getattr(args, "run_mode", None):
        command.extend(["--run-mode", str(args.run_mode)])
    if getattr(args, "target", None):
        command.extend(["--target", str(args.target)])
    for attr, flag in (
        ("wave_start", "--wave-start"),
        ("wave_end", "--wave-end"),
        ("wave_window", "--wave-window"),
        ("wave_margin", "--wave-margin"),
    ):
        value = getattr(args, attr, None)
        if value:
            command.extend([flag, str(value)])
    if getattr(args, "timeout", None) is not None:
        command.extend(["--timeout", str(args.timeout)])
    if getattr(args, "rebuild", False):
        command.append("--rebuild")
    _append_repeat_option(command, "--define", getattr(args, "define", None))
    _append_repeat_option(command, "--comp-arg", getattr(args, "comp_arg", None))
    _append_repeat_option(command, "--c-arg", getattr(args, "c_arg", None))
    _append_repeat_option(command, "--sim-arg", getattr(args, "sim_arg", None))
    _append_repeat_option(command, "--plusarg", getattr(args, "plusarg", None))
    return " ".join(shlex.quote(part) for part in command)


def retention_policy(args: Any) -> str:
    explicit = getattr(args, "wave_retention", None)
    if explicit:
        return str(explicit)
    if bool(getattr(args, "_wave_debug_rerun", False)) or waves_on_fail_requested(args):
        return "failed"
    if waves_requested(args):
        return "all"
    return "none"


def apply_wave_retention(waves_dir: Path, status: str, retention: str, dry_run: bool) -> str:
    if retention == "none":
        if waves_dir.exists() and not dry_run:
            shutil.rmtree(waves_dir)
        return "pruned"
    if retention == "failed" and status not in NON_PASS_STATUSES:
        if waves_dir.exists() and not dry_run:
            shutil.rmtree(waves_dir)
        return "pruned_pass"
    return "kept"


def build_wave_metadata(
    *,
    args: Any,
    root: Path,
    flow_name: str,
    item: str,
    seed: int,
    tool: str,
    wave_format: str,
    waves_dir: Path,
    log_path: Path,
    script_path: Path,
    env_path: Path,
    result_json_path: Path,
    status: str,
    range_info: dict[str, Any],
    backend_range_supported: bool,
) -> tuple[dict[str, Any], list[str], str]:
    retention = retention_policy(args)
    dry_run = bool(getattr(args, "dry_run", False))
    retention_action = apply_wave_retention(waves_dir, status, retention, dry_run)
    files = (
        discovered_wave_paths(waves_dir, item, tool, wave_format)
        if dry_run
        else actual_wave_paths(waves_dir, item, tool, wave_format)
    )
    rel_files = [repo_rel(root, path) or str(path) for path in files]
    rel_dir = repo_rel(root, waves_dir) or str(waves_dir)
    viewer_cmds = viewer_commands(rel_files, wave_format)
    replay_cmd = same_seed_replay_command(
        flow_name=flow_name,
        item=item,
        seed=seed,
        tool=tool,
        wave_format=wave_format,
        args=args,
    )
    mode = "on_fail" if bool(getattr(args, "_wave_debug_rerun", False)) else "always"
    metadata: dict[str, Any] = {
        "requested": True,
        "mode": mode,
        "format": wave_format,
        "directory": rel_dir,
        "files": rel_files,
        "viewer_commands": viewer_cmds,
        "same_seed_replay": replay_cmd,
        "retention": retention,
        "retention_action": retention_action,
        "range_supported": backend_range_supported,
    }
    range_meta = wave_range_metadata(range_info)
    if range_meta:
        metadata["range"] = range_meta
        if not backend_range_supported:
            metadata["range_note"] = (
                "requested range recorded, but this backend path does not enforce ranged dumping"
            )
    if retention_action == "kept":
        copied_log = waves_dir / log_path.name
        context_json = waves_dir / "debug_context.json"
        metadata["copied_log"] = repo_rel(root, copied_log) or str(copied_log)
        metadata["debug_context_json"] = repo_rel(root, context_json) or str(context_json)
        if not bool(getattr(args, "dry_run", False)):
            waves_dir.mkdir(parents=True, exist_ok=True)
            if log_path.is_file():
                shutil.copy2(log_path, copied_log)
            context = {
                "schema_version": 1,
                "flow": flow_name,
                "item": item,
                "seed": seed,
                "tool": tool,
                "status": status,
                "mode": mode,
                "format": wave_format,
                "waves": {
                    "directory": rel_dir,
                    "files": rel_files,
                    "range": metadata.get("range"),
                    "range_supported": backend_range_supported,
                },
                "log": repo_rel(root, log_path) or str(log_path),
                "copied_log": metadata["copied_log"],
                "script": repo_rel(root, script_path) or str(script_path),
                "env": repo_rel(root, env_path) or str(env_path),
                "result_json": repo_rel(root, result_json_path) or str(result_json_path),
                "viewer_commands": viewer_cmds,
                "same_seed_replay": replay_cmd,
            }
            context_json.write_text(
                json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    return metadata, rel_files, rel_dir
