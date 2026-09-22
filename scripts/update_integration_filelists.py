#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate portable simulation and synthesis filelists for integrators."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "integration/filelists"
SYSTEMS = ("smu", "smc", "dtp", "aou")
DV_SYSTEMS = SYSTEMS[:3]
DV_TOOLS = ("verilator", "vcs")
FILELIST_NAMES = (
    *(f"{system}.{tool}.sim.f" for system in DV_SYSTEMS for tool in DV_TOOLS),
    "aou.sim.f",
    *(f"{system}.synth.f" for system in SYSTEMS),
)


def generate_dv_filelist(system: str, tool: str, output: Path) -> None:
    config = ROOT / f"hw/sys/{system}/dv/{system}_sim_cfg.toml"
    build = tomllib.loads(config.read_text(encoding="utf-8"))["build"]
    subprocess.run(
        [
            sys.executable,
            "tools/dv/run_dv.py",
            "--dut",
            system,
            "--tool",
            tool,
            "--stage",
            "flist",
            "--quiet",
        ],
        cwd=ROOT,
        check=True,
    )
    bender = ROOT / build["bender_filelist"]
    combined = ROOT / build["filelist"]
    lines: list[str] = []
    for line in combined.read_text(encoding="utf-8").splitlines():
        if line == f"-f {bender}":
            lines.extend(bender.read_text(encoding="utf-8").splitlines())
        else:
            lines.append(line)
    root_prefix = f"{ROOT}/"
    (output / f"{system}.{tool}.sim.f").write_text(
        "\n".join(line.replace(root_prefix, "") for line in lines) + "\n",
        encoding="utf-8",
    )


def generate(output: Path) -> None:
    shutil.rmtree(output, ignore_errors=True)
    subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-f",
            "ocah.mk",
            f"BLOCK={' '.join(SYSTEMS)}",
            f"OCAH_INTEGRATION_FILELIST_DIR={output}",
            "ocah-integration-filelists-all",
        ],
        cwd=ROOT,
        check=True,
    )
    for system in DV_SYSTEMS:
        for tool in DV_TOOLS:
            generate_dv_filelist(system, tool, output)


def contents(root: Path) -> dict[str, bytes | None]:
    return {path.name: path.read_bytes() if path.is_file() else None for path in root.iterdir()}


def check() -> int:
    with tempfile.TemporaryDirectory(prefix="ocah-integration-filelists-") as directory:
        expected_root = Path(directory) / "filelists"
        generate(expected_root)
        actual = contents(OUTPUT) if OUTPUT.exists() else {}
        expected = {
            name: (expected_root / name).read_bytes() if (expected_root / name).is_file() else None
            for name in FILELIST_NAMES
        }
        problems = {
            "missing": expected.keys() - actual.keys(),
            "extra": actual.keys() - expected.keys(),
            "stale": {
                name for name in actual.keys() & expected.keys() if actual[name] != expected[name]
            },
        }
        for reason, names in problems.items():
            for name in sorted(names):
                print(f"{reason}: integration/filelists/{name}", file=sys.stderr)
        return int(any(problems.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check committed filelists")
    args = parser.parse_args()
    try:
        if args.check:
            return check()
        generate(OUTPUT)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"updated {len(FILELIST_NAMES)} integration filelists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
