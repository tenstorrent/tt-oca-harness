#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Build and stage the firmware images the SMU wrapper testbench boots.

Two producers share one toolchain decision:

* this DV root's freestanding images (SMC smoke ROM, SMC arm ROMs, SEP smoke
  TCM image, SEP boot-ROM trampoline), selected with ``--target``;
* the SEP and SMC DV firmware engines (``hw/sys/<sys>/dv/fw/fw.mk``, picolibc
  plus each subsystem's runtime library), one image per ``--sep-test`` /
  ``--smc-test``.

Toolchain contract: the caller's ``RISCV_TOOLCHAIN`` (and ``RISCV_PREFIX``)
wins when that gcc has picolibc. Otherwise the whole invocation re-runs inside
the OCAH toolchain container through ``scripts/docker-run.sh run-here``.
``--toolchain host`` (what the container path passes to itself) is the only
mode that takes the tools from PATH.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

FW_ROOT = Path(__file__).resolve().parent
DV_ROOT = FW_ROOT.parent
REPO_ROOT = FW_ROOT.parents[4]
COMMON = FW_ROOT / "common"
TESTS = FW_ROOT / "tests"
BUILD_ROOT = DV_ROOT / "build" / "firmware"
PRELOAD_DIR = BUILD_ROOT / "preloads"
DOCKER_RUN = REPO_ROOT / "scripts" / "docker-run.sh"

DEFAULT_PREFIX = "riscv64-unknown-elf-"
ALTERNATE_PREFIX = "riscv-none-elf-"
ENGINE_DIRS = {
    "sep": REPO_ROOT / "hw" / "sys" / "sep" / "dv" / "fw",
    "smc": REPO_ROOT / "hw" / "sys" / "smc" / "dv" / "fw",
}

TARGETS = (
    "preloads",
    "smu_smc_smoke",
    "smu_smc_fabric",
    "smu_sep_arm",
    "smu_sep_smoke",
    "smu_sep_bidirect",
    "all",
)


@dataclass(frozen=True)
class Toolchain:
    """``directory`` is empty when the tools are taken from PATH."""

    directory: str
    prefix: str

    def tool(self, name: str) -> str:
        if self.directory:
            return str(Path(self.directory) / f"{self.prefix}{name}")
        return f"{self.prefix}{name}"


def _has_picolibc(gcc: str) -> bool:
    try:
        result = subprocess.run(
            [gcc, "-specs=picolibc.specs", "-E", "-"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _caller_toolchain(allow_path: bool) -> Toolchain | None:
    directory = os.environ.get("RISCV_TOOLCHAIN", "")
    prefix = os.environ.get("RISCV_PREFIX", "")
    if directory:
        if not prefix:
            prefix = DEFAULT_PREFIX
            default_gcc = Path(directory) / f"{DEFAULT_PREFIX}gcc"
            alternate_gcc = Path(directory) / f"{ALTERNATE_PREFIX}gcc"
            if not os.access(default_gcc, os.X_OK) and os.access(alternate_gcc, os.X_OK):
                prefix = ALTERNATE_PREFIX
        toolchain = Toolchain(directory, prefix)
    elif allow_path:
        toolchain = Toolchain("", prefix or DEFAULT_PREFIX)
    else:
        return None
    return toolchain if _has_picolibc(toolchain.tool("gcc")) else None


def _run(argv: Sequence[str]) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, check=True)


def _write_byte_hex(binary: Path, output: Path) -> None:
    data = binary.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{byte:02x}\n" for byte in data), encoding="ascii")


def _write_word64_hex(binary: Path, output: Path) -> None:
    data = binary.read_bytes()
    data += bytes((-len(data)) % 8)
    words = [
        int.from_bytes(data[offset : offset + 8], byteorder="little")
        for offset in range(0, len(data), 8)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{word:016x}\n" for word in words), encoding="ascii")


def _compile(
    toolchain: Toolchain,
    *,
    arch: str,
    abi: str,
    linker: Path,
    sources: list[Path],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            toolchain.tool("gcc"),
            f"-march={arch}",
            f"-mabi={abi}",
            "-mcmodel=medany",
            "-mstrict-align",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-nostdlib",
            "-nostartfiles",
            "-Wl,--gc-sections",
            "-Wl,--no-relax",
            "-Wl,--build-id=none",
            "-T",
            str(linker),
            *(str(source) for source in sources),
            "-o",
            str(output),
        ]
    )


def build_smc_rom(
    toolchain: Toolchain, test_name: str, start: Path = COMMON / "smc_start.S"
) -> Path:
    test_dir = TESTS / test_name
    output_dir = BUILD_ROOT / test_name
    elf = output_dir / f"{test_name}.elf"
    binary = output_dir / f"{test_name}.bin"
    rom_hex = output_dir / f"{test_name}.rom.hex"
    _compile(
        toolchain,
        arch="rv64imac_zicsr_zifencei",
        abi="lp64",
        linker=COMMON / "smc_rom.ld",
        sources=[start, test_dir / "main.c"],
        output=elf,
    )
    _run([toolchain.tool("objcopy"), "-O", "binary", str(elf), str(binary)])
    _write_word64_hex(binary, rom_hex)
    return rom_hex


def build_sep_firmware(toolchain: Toolchain) -> tuple[Path, Path, Path]:
    test_name = "smu_sep_smoke"
    test_dir = TESTS / test_name
    output_dir = BUILD_ROOT / test_name
    elf = output_dir / f"{test_name}.elf"
    itcm_bin = output_dir / f"{test_name}.itcm.bin"
    dtcm_bin = output_dir / f"{test_name}.dtcm.bin"
    itcm_hex = output_dir / f"{test_name}.itcm.hex"
    dtcm_hex = output_dir / f"{test_name}.dtcm.hex"
    symbols = output_dir / f"{test_name}.sym"
    _compile(
        toolchain,
        arch="rv32imc_zicsr_zifencei",
        abi="ilp32",
        linker=COMMON / "sep_tcm.ld",
        sources=[COMMON / "sep_start.S", test_dir / "main.c"],
        output=elf,
    )
    objcopy = toolchain.tool("objcopy")
    _run([objcopy, "-O", "binary", "--only-section=.text", str(elf), str(itcm_bin)])
    _write_byte_hex(itcm_bin, itcm_hex)
    try:
        _run([objcopy, "-O", "binary", "--only-section=.data", str(elf), str(dtcm_bin)])
    except subprocess.CalledProcessError:
        dtcm_bin.write_bytes(b"")
    _write_byte_hex(dtcm_bin, dtcm_hex)
    with symbols.open("w", encoding="utf-8") as stream:
        subprocess.run([toolchain.tool("nm"), "-n", str(elf)], check=True, stdout=stream)
    return itcm_hex, dtcm_hex, symbols


def build_sep_boot_rom(toolchain: Toolchain) -> Path:
    output_dir = BUILD_ROOT / "boot_rom"
    elf = output_dir / "smu_sep_boot_rom.elf"
    binary = output_dir / "smu_sep_boot_rom.bin"
    rom_hex = output_dir / "smu_sep_boot_rom.hex"
    _compile(
        toolchain,
        arch="rv32imc_zicsr_zifencei",
        abi="ilp32",
        linker=COMMON / "sep_boot_rom.ld",
        sources=[COMMON / "sep_boot_rom.S"],
        output=elf,
    )
    _run([toolchain.tool("objcopy"), "-O", "binary", str(elf), str(binary)])
    _write_word64_hex(binary, rom_hex)
    return rom_hex


def build_engine_test(toolchain: Toolchain, engine: str, test_name: str) -> None:
    """Build one image of the shared DV firmware engine (hw/common/dv/fw/compile.mk).

    RISCV_TOOLCHAIN + RISCV_PREFIX is the only toolchain contract compile.mk
    accepts; an empty RISCV_TOOLCHAIN makes it take the prefixed tools from PATH.
    """
    _run(
        [
            "make",
            "-C",
            str(ENGINE_DIRS[engine]),
            "-f",
            "fw.mk",
            "dv-fw-tests",
            f"TEST={test_name}",
            f"OCAH_ROOT={REPO_ROOT}",
            f"RISCV_TOOLCHAIN={toolchain.directory}",
            f"RISCV_PREFIX={toolchain.prefix}",
        ]
    )


def gen_preloads() -> None:
    """Generate the deterministic default preload images.

    These are blank (all-zero) memory contents in the formats the SV loaders
    expect: word64 lines for the SMC ROM / SEP boot-ROM models, byte lines
    for the SEP ICCM/DCCM shim, and word lines for the eFuse OTP responder.
    No RISC-V toolchain is required, so the elaboration tests stay runnable
    on a source-only setup.
    """
    PRELOAD_DIR.mkdir(parents=True, exist_ok=True)
    word64_zeros = ("0" * 16 + "\n") * 16
    word32_zeros = ("0" * 8 + "\n") * 16
    byte_zeros = ("00\n") * 16
    images = {
        "smc_rom_default.hex": word64_zeros,
        "sep_boot_rom_default.hex": word64_zeros,
        "smc_efuse_default.hex": word32_zeros,
        "sep_efuse_default.hex": word32_zeros,
        "sep_itcm_default.hex": byte_zeros,
        "sep_dtcm_default.hex": byte_zeros,
    }
    for name, content in images.items():
        (PRELOAD_DIR / name).write_text(content, encoding="ascii")
        print(f"+ generated {PRELOAD_DIR / name}", flush=True)


def run_in_container(args: argparse.Namespace) -> int:
    """Re-run this invocation inside the OCAH toolchain container.

    docker-run.sh does not forward the caller's environment, but its bwrap
    backend does. RISCV_TOOLCHAIN and RISCV_PREFIX are dropped so the
    container path resolves the image's own tools from PATH. UV and
    VIRTUAL_ENV are dropped for the same reason: ``uv run`` exports UV as the
    host binary, preamble.mk keeps that value, and the sandbox does not bind
    it. With UV unset, ``uv`` resolves on PATH to the binary mounted at
    /run/ocah/uv. The project environment, cache and managed interpreters stay
    under local/ so ``uv run --locked`` does not replace the host .venv or
    store interpreters under the shared /tmp the sandbox uses as HOME.
    """
    if not os.access(DOCKER_RUN, os.X_OK):
        print(
            "error: no picolibc-enabled RISC-V toolchain: set RISCV_TOOLCHAIN "
            f"(and RISCV_PREFIX), or provide {DOCKER_RUN}",
            file=sys.stderr,
        )
        return 1
    argv = [
        str(DOCKER_RUN),
        "run-here",
        "python3",
        str(Path(__file__).resolve()),
        "--target",
        args.target,
        "--toolchain",
        "host",
    ]
    for test_name in args.sep_test:
        argv += ["--sep-test", test_name]
    for test_name in args.smc_test:
        argv += ["--smc-test", test_name]
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "RISCV_TOOLCHAIN",
            "RISCV_PREFIX",
            "MAKEFLAGS",
            "MFLAGS",
            "UV",
            "VIRTUAL_ENV",
        }
    }
    sandbox = REPO_ROOT / "local"
    env["UV_PROJECT_ENVIRONMENT"] = str(sandbox / "bwrap-venv")
    env["UV_CACHE_DIR"] = str(sandbox / "bwrap-uv-cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(sandbox / "bwrap-uv-python")
    print("+", " ".join(argv), flush=True)
    return subprocess.run(argv, cwd=REPO_ROOT, env=env, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument(
        "--sep-test",
        action="append",
        default=[],
        metavar="NAME",
        help="also build this SEP DV firmware engine image (hw/sys/sep/dv/fw/tests/NAME)",
    )
    parser.add_argument(
        "--smc-test",
        action="append",
        default=[],
        metavar="NAME",
        help="also build this SMC DV firmware engine image (hw/sys/smc/dv/fw/tests/NAME)",
    )
    parser.add_argument(
        "--toolchain",
        choices=("auto", "host", "container"),
        default="auto",
        help="auto: RISCV_TOOLCHAIN when it has picolibc, else the container; "
        "host: RISCV_TOOLCHAIN or PATH, no container fallback; "
        "container: always the container",
    )
    args = parser.parse_args()

    gen_preloads()
    needs_toolchain = args.target != "preloads" or args.sep_test or args.smc_test
    if not needs_toolchain:
        return 0

    toolchain = None
    if args.toolchain != "container":
        toolchain = _caller_toolchain(allow_path=args.toolchain == "host")
    if toolchain is None:
        if args.toolchain == "host":
            print(
                "error: no picolibc-enabled RISC-V toolchain on RISCV_TOOLCHAIN or PATH",
                file=sys.stderr,
            )
            return 1
        print(
            "build_firmware: no caller RISCV_TOOLCHAIN with picolibc; "
            "building in the OCAH toolchain container",
            flush=True,
        )
        return run_in_container(args)

    if args.target in ("smu_smc_smoke", "all"):
        build_smc_rom(toolchain, "smu_smc_smoke")
    if args.target in ("smu_smc_fabric", "all"):
        # Runs on every hart, so it takes the entry that gives each its own stack.
        build_smc_rom(toolchain, "smu_smc_fabric", COMMON / "smc_mp_start.S")
    if args.target in ("smu_sep_arm", "smu_sep_smoke", "all"):
        build_smc_rom(toolchain, "smu_sep_arm")
    if args.target in ("smu_sep_smoke", "all"):
        build_sep_firmware(toolchain)
    if args.target in ("smu_sep_bidirect", "all"):
        # SMC half of the SEP<->SMC handshake; the SEP half is the engine image
        # sep_smu_bidirect.
        build_smc_rom(toolchain, "smu_sep_bidirect_arm")
    if args.target in ("smu_sep_arm", "smu_sep_smoke", "smu_sep_bidirect", "all"):
        build_sep_boot_rom(toolchain)
    for test_name in args.sep_test:
        build_engine_test(toolchain, "sep", test_name)
    for test_name in args.smc_test:
        build_engine_test(toolchain, "smc", test_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
