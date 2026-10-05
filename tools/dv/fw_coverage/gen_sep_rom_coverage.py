# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate per-variant SEP Boot ROM firmware coverage reports."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fw_coverage.renode_trace import TRACE_NAME
from runlib.results import run_is_complete

ELF_NAME = "boot_rom.elf"
BOOT_ROM_MODES = ("boot_rom", "boot_rom_pio")
RENODE_VERSION = "v1.16.1"
RENODE_REVISION = "d66b0c2aa3d420408eccecfd1d3bab0fd702a6db"
RENODE_URL = "https://github.com/renode/renode.git"
INFO_PROCESS_REVISION = "4c661cd6cb18df8ecfab7118cc0acbf4218b302a"
INFO_PROCESS_URL = "https://github.com/antmicro/info-process.git"
COVERVIEW_REVISION = "15386d3b85712ab69e3a34cbc8a1ddd579cb14ad"
COVERVIEW_URL = "https://github.com/antmicro/coverview.git"


class CoverageError(RuntimeError):
    """Raised when run artifacts are incomplete or inconsistent."""


@dataclass(frozen=True)
class TraceInput:
    item: str
    mode: str
    leaf_dir: Path
    trace: Path
    elf: Path
    elf_sha256: str


@dataclass(frozen=True)
class SkippedTrace:
    item: str
    trace: Path
    reason: str


@dataclass(frozen=True)
class CoverageTools:
    python: Path
    retracer: Path
    info_process: Path
    coverview: Path


@dataclass(frozen=True)
class VariantOutputs:
    info_zip: Path
    info_json: Path
    html_dir: Path


def load_firmware_modes(testlist: Path) -> dict[str, str]:
    """Map each SEP ROM test name to its Boot ROM firmware build mode."""
    with testlist.open("rb") as stream:
        data = tomllib.load(stream)
    modes: dict[str, str] = {}
    for test in data.get("tests", []):
        firmware = test.get("firmware")
        if not isinstance(firmware, dict):
            continue
        name = test.get("name")
        mode = firmware.get("mode")
        if isinstance(name, str) and mode in BOOT_ROM_MODES:
            modes[name] = mode
    return modes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_gzip(path: Path) -> bool:
    try:
        with gzip.open(path, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
    except (OSError, EOFError):
        return False
    return True


def _trace_has_pc(path: Path) -> bool:
    with gzip.open(path, "rb") as stream:
        return len(stream.read()) > 10


def _leaf_identity(result_path: Path) -> tuple[str, int, int] | None:
    try:
        attempt = int(result_path.parent.name.removeprefix("attempt_"))
        seed = int(result_path.parent.parent.name.removeprefix("seed_"))
    except ValueError:
        return None
    if not result_path.parent.name.startswith("attempt_"):
        return None
    if not result_path.parent.parent.name.startswith("seed_"):
        return None
    return result_path.parent.parent.parent.name, seed, attempt


def discover_trace_inputs(
    run_dir: Path, firmware_modes: dict[str, str]
) -> tuple[list[TraceInput], list[SkippedTrace]]:
    """Select each seed's final passing non-debug trace and leaf-local ELF."""
    inputs: list[TraceInput] = []
    skipped: list[SkippedTrace] = []
    final_results: dict[tuple[str, int], tuple[int, Path, dict | None, str | None]] = {}
    for result_path in sorted(run_dir.rglob("result.json")):
        path_identity = _leaf_identity(result_path)
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if path_identity is not None:
                item, seed, attempt = path_identity
                if item in firmware_modes:
                    key = (item, seed)
                    previous = final_results.get(key)
                    if previous is None or attempt > previous[0]:
                        final_results[key] = (
                            attempt,
                            result_path,
                            None,
                            f"invalid result.json: {exc}",
                        )
            continue

        if path_identity is None:
            item = result.get("item")
            seed = result.get("seed")
            attempt = result.get("attempt")
            if (
                not isinstance(item, str)
                or result_path.parent.name != item
                or not isinstance(seed, int)
                or not isinstance(attempt, int)
            ):
                continue
            identity = (item, seed, attempt)
        else:
            identity = path_identity

        item, seed, attempt = identity
        if item not in firmware_modes:
            continue
        key = (item, seed)
        previous = final_results.get(key)
        if (
            path_identity is not None
            and (
                result.get("item"),
                result.get("seed"),
                result.get("attempt"),
            )
            != identity
        ):
            if previous is None or attempt > previous[0]:
                final_results[key] = (
                    attempt,
                    result_path,
                    None,
                    "result item/seed/attempt does not match leaf path",
                )
            continue
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and metadata.get("debug_only") is True:
            continue
        if previous is None or attempt > previous[0]:
            final_results[key] = (attempt, result_path, result, None)

    for _attempt, result_path, result, result_error in sorted(final_results.values()):
        leaf_dir = result_path.parent
        trace = leaf_dir / TRACE_NAME
        if result is None:
            identity = _leaf_identity(result_path)
            if identity is None:
                raise CoverageError(f"invalid leaf result path: {result_path}")
            item = identity[0]
            skipped.append(SkippedTrace(item, trace, str(result_error)))
            continue
        item = str(result["item"])
        mode = firmware_modes[item]
        if result.get("status") != "PASS":
            skipped.append(SkippedTrace(item, trace, f"leaf status is {result.get('status')}"))
            continue
        if not trace.is_file():
            skipped.append(SkippedTrace(item, trace, "coverage trace is missing"))
            continue
        if not _valid_gzip(trace):
            skipped.append(SkippedTrace(item, trace, "trace gzip is incomplete or corrupt"))
            continue
        if not _trace_has_pc(trace):
            skipped.append(SkippedTrace(item, trace, "trace contains no retired PCs"))
            continue
        elf = leaf_dir / ELF_NAME
        if not elf.is_file() or elf.stat().st_size == 0:
            skipped.append(SkippedTrace(item, trace, "leaf-local boot_rom.elf is missing"))
            continue
        inputs.append(TraceInput(item, mode, leaf_dir, trace, elf, _sha256(elf)))
    return inputs, skipped


def group_trace_inputs(inputs: list[TraceInput]) -> dict[str, list[TraceInput]]:
    """Group traces by firmware mode and reject mixed ELFs within a mode."""
    grouped: dict[str, list[TraceInput]] = {}
    for entry in inputs:
        grouped.setdefault(entry.mode, []).append(entry)
    for mode, entries in grouped.items():
        hashes = {entry.elf_sha256 for entry in entries}
        if len(hashes) != 1:
            raise CoverageError(
                f"{mode} traces refer to different ELF images; do not merge different builds"
            )
    return grouped


def validate_variant_groups(
    grouped: dict[str, list[TraceInput]],
    run_result: dict,
    firmware_modes: dict[str, str],
) -> None:
    """Require a report group for every firmware variant selected by the run."""
    selected = run_result.get("items")
    if not isinstance(selected, list):
        return
    expected = {firmware_modes[item] for item in selected if item in firmware_modes}
    missing = sorted(expected - grouped.keys())
    if missing:
        raise CoverageError(
            "no passing, complete trace is available for selected variant(s): " + ", ".join(missing)
        )


RunCommand = Callable[..., subprocess.CompletedProcess]


def render_variant(
    mode: str,
    entries: list[TraceInput],
    output_dir: Path,
    sources: Sequence[Path],
    tools: CoverageTools,
    *,
    run: RunCommand = subprocess.run,
) -> VariantOutputs:
    """Retrace and render one group whose traces share an ELF."""
    if not entries:
        raise CoverageError(f"{mode} has no traces")
    variant_dir = output_dir / mode
    variant_dir.mkdir(parents=True, exist_ok=True)
    info_zip = variant_dir / "coverage.info.zip"
    info_json = variant_dir / "coverage.info.json"
    html_dir = variant_dir / "html"
    command = [
        str(tools.retracer),
        "coverage",
        *(str(entry.trace) for entry in entries),
        "--binary",
        str(entries[0].elf),
        "--sources",
        *(str(path) for path in sources),
        "--export-for-coverview",
        "--output",
        str(info_zip),
    ]
    run(command, check=True)
    run(
        [
            str(tools.info_process),
            "report",
            "--pretty-print",
            "--output",
            str(info_json),
            str(info_zip),
        ],
        check=True,
    )
    run(["npm", "run", "build"], cwd=tools.coverview, check=True)
    run(
        [str(tools.python), str(tools.coverview / "embed.py"), "--inject-data", str(info_zip)],
        cwd=tools.coverview,
        check=True,
    )
    if html_dir.exists():
        shutil.rmtree(html_dir)
    shutil.copytree(tools.coverview / "dist", html_dir)
    return VariantOutputs(info_zip, info_json, html_dir)


def write_index(output_dir: Path, variants: dict[str, tuple[str, int]]) -> None:
    """Write a small landing page linking the independently mapped variants."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        '      <li><a href="{}">{}</a> — {} passing trace(s)</li>'.format(
            html.escape(path, quote=True), html.escape(mode), count
        )
        for mode, (path, count) in sorted(variants.items())
    )
    (output_dir / "index.html").write_text(
        """<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>SEP Boot ROM firmware coverage</title></head>
  <body>
    <h1>SEP Boot ROM firmware coverage</h1>
    <p>Each report uses the exact ELF staged with that firmware variant.</p>
    <ul>
{}
    </ul>
  </body>
</html>
""".format(rows),
        encoding="utf-8",
    )


def _require_program(name: str) -> None:
    if shutil.which(name) is None:
        raise CoverageError(f"required program is not on PATH: {name}")


def coverage_cache_path(cache_root: Path) -> Path:
    """Return the immutable pin-set directory below a caller's cache root."""
    return cache_root / (
        f"renode-{RENODE_REVISION[:12]}_"
        f"info-{INFO_PROCESS_REVISION[:12]}_"
        f"coverview-{COVERVIEW_REVISION[:12]}"
    )


def _checkout(
    path: Path,
    url: str,
    revision: str,
    *,
    run: RunCommand,
) -> None:
    if path.is_dir():
        try:
            current = run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            current = ""
        if current != revision:
            shutil.rmtree(path)
    if not path.is_dir():
        run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(path)], check=True)
        run(["git", "-C", str(path), "checkout", "--detach", revision], check=True)


def _stamp_matches(path: Path, revision: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").strip() == revision
    except OSError:
        return False


def prepare_tools(cache_dir: Path, *, run: RunCommand = subprocess.run) -> CoverageTools:
    """Install pinned report tools into a reusable scratch cache."""
    _require_program("git")
    _require_program("npm")
    cache_dir = coverage_cache_path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    venv = cache_dir / "venv"
    python = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    retracer = venv / "bin" / "renode-retracer"
    info_process = venv / "bin" / "info-process"
    renode = cache_dir / "renode"
    coverview = cache_dir / "coverview"
    retracer_stamp = cache_dir / "execution-tracer.complete"
    info_stamp = cache_dir / "info-process.complete"

    if not python.is_file() or not pip.is_file():
        if venv.exists():
            shutil.rmtree(venv)
        run([sys.executable, "-m", "venv", str(venv)], check=True)
    if not retracer.is_file() or not _stamp_matches(retracer_stamp, RENODE_REVISION):
        _checkout(renode, RENODE_URL, RENODE_REVISION, run=run)
        run(
            [
                str(pip),
                "install",
                "--force-reinstall",
                str(renode / "tools/execution_tracer"),
            ],
            check=True,
        )
        retracer_stamp.write_text(f"{RENODE_REVISION}\n", encoding="utf-8")
    if not info_process.is_file() or not _stamp_matches(info_stamp, INFO_PROCESS_REVISION):
        run(
            [
                str(pip),
                "install",
                "--force-reinstall",
                f"git+{INFO_PROCESS_URL}@{INFO_PROCESS_REVISION}",
            ],
            check=True,
        )
        info_stamp.write_text(f"{INFO_PROCESS_REVISION}\n", encoding="utf-8")
    _checkout(coverview, COVERVIEW_URL, COVERVIEW_REVISION, run=run)
    npm_stamp = coverview / ".npm-ci.complete"
    if not (coverview / "node_modules").is_dir() or not _stamp_matches(
        npm_stamp, COVERVIEW_REVISION
    ):
        if (coverview / "node_modules").exists():
            shutil.rmtree(coverview / "node_modules")
        run(["npm", "ci"], cwd=coverview, check=True)
        npm_stamp.write_text(f"{COVERVIEW_REVISION}\n", encoding="utf-8")

    missing = [
        path
        for path in (
            python,
            retracer,
            info_process,
            coverview / "embed.py",
            coverview / "node_modules",
        )
        if not path.exists()
    ]
    if missing:
        raise CoverageError(f"coverage tool setup incomplete: {', '.join(map(str, missing))}")
    return CoverageTools(python, retracer, info_process, coverview)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_output_dir(root: Path, run_dir: Path) -> Path:
    return root / "tools/dv/fw_coverage/output" / run_dir.name


def _source_files(root: Path) -> list[Path]:
    bootrom = root / "hw/sys/sep/bootrom/prod"
    return sorted(
        path
        for directory in (bootrom / "src", bootrom / "include")
        for path in directory.rglob("*")
        if path.suffix in {".c", ".h"}
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate per-variant SEP Boot ROM firmware coverage reports."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Report root (default: tools/dv/fw_coverage/output/<run-directory-name>)",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        help="Pinned tool cache (default: $TMPDIR/ocah-fw-coverage-tools)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = _repo_root()
    run_dir = args.run_dir.expanduser().resolve()
    output_dir = (args.output_dir or default_output_dir(root, run_dir)).expanduser().resolve()

    result_path = run_dir / "result.json"
    try:
        run_result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageError(f"cannot read run result {result_path}: {exc}") from exc
    if run_result.get("flow") != "sep":
        raise CoverageError(f"{result_path} is not a SEP run")
    if not run_is_complete(run_result):
        raise CoverageError(f"{result_path} records an incomplete or interrupted run")

    testlist = root / "hw/sys/sep/dv/testlists/rom_fw.toml"
    firmware_modes = load_firmware_modes(testlist)
    inputs, skipped = discover_trace_inputs(run_dir, firmware_modes)
    for entry in skipped:
        print(f"SKIP {entry.item}: {entry.reason} ({entry.trace})", file=sys.stderr)
    if not inputs:
        raise CoverageError(f"no passing {TRACE_NAME} artifacts found under {run_dir}")
    grouped = group_trace_inputs(inputs)
    validate_variant_groups(grouped, run_result, firmware_modes)
    if args.tools_dir is not None:
        tools_dir = args.tools_dir.expanduser().resolve()
    else:
        tmpdir = os.environ.get("TMPDIR")
        if not tmpdir:
            raise CoverageError("TMPDIR is unset; set it to the repository-approved scratch area")
        tools_dir = Path(tmpdir).expanduser().resolve() / "ocah-fw-coverage-tools"
    tools = prepare_tools(tools_dir)
    sources = _source_files(root)
    if not sources:
        raise CoverageError("SEP Boot ROM source files were not found")

    links: dict[str, tuple[str, int]] = {}
    manifest_variants: dict[str, object] = {}
    for mode, entries in sorted(grouped.items()):
        outputs = render_variant(mode, entries, output_dir, sources, tools)
        links[mode] = (str(outputs.html_dir.relative_to(output_dir) / "index.html"), len(entries))
        manifest_variants[mode] = {
            "elf": str(entries[0].elf),
            "elf_sha256": entries[0].elf_sha256,
            "traces": [str(entry.trace) for entry in entries],
            "items": [entry.item for entry in entries],
            "html": str(outputs.html_dir),
            "json": str(outputs.info_json),
        }
    write_index(output_dir, links)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "source_commit": run_result.get("git", {}).get("commit"),
                "source_dirty": run_result.get("git", {}).get("dirty"),
                "variants": manifest_variants,
                "skipped": [
                    {"item": entry.item, "trace": str(entry.trace), "reason": entry.reason}
                    for entry in skipped
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"SEP Boot ROM firmware coverage: {output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CoverageError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
