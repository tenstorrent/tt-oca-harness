#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Build and stage the self-contained SMU OSS smoke firmware images."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


FW_ROOT = Path(__file__).resolve().parent
DV_ROOT = FW_ROOT.parent
COMMON = FW_ROOT / "common"
TESTS = FW_ROOT / "tests"
BUILD_ROOT = DV_ROOT / "build" / "firmware"
PRELOAD_DIR = BUILD_ROOT / "preloads"


def _tool(name: str) -> str:
    override = os.environ.get(f"RISCV_{name.upper()}")
    if override:
        return override
    prefix = os.environ.get("RISCV_TOOLCHAIN")
    if prefix:
        candidate = Path(prefix) / f"riscv64-unknown-elf-{name}"
        if candidate.is_file():
            return str(candidate)
    candidate = shutil.which(f"riscv64-unknown-elf-{name}")
    if candidate:
        return candidate
    tools_soc = Path("/tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10/bin")
    candidate = tools_soc / f"riscv64-unknown-elf-{name}"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(
        f"riscv64-unknown-elf-{name} not found; set RISCV_TOOLCHAIN or RISCV_{name.upper()}"
    )


def _run(argv: list[str]) -> None:
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
            _tool("gcc"),
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


def build_smc_rom(test_name: str) -> Path:
    test_dir = TESTS / test_name
    output_dir = BUILD_ROOT / test_name
    elf = output_dir / f"{test_name}.elf"
    binary = output_dir / f"{test_name}.bin"
    rom_hex = output_dir / f"{test_name}.rom.hex"
    _compile(
        arch="rv64imac_zicsr_zifencei",
        abi="lp64",
        linker=COMMON / "smc_rom.ld",
        sources=[COMMON / "smc_start.S", test_dir / "main.c"],
        output=elf,
    )
    _run([_tool("objcopy"), "-O", "binary", str(elf), str(binary)])
    _write_word64_hex(binary, rom_hex)
    return rom_hex


def build_sep_firmware() -> tuple[Path, Path, Path]:
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
        arch="rv32imc_zicsr_zifencei",
        abi="ilp32",
        linker=COMMON / "sep_tcm.ld",
        sources=[COMMON / "sep_start.S", test_dir / "main.c"],
        output=elf,
    )
    _run(
        [
            _tool("objcopy"),
            "-O",
            "binary",
            "--only-section=.text",
            str(elf),
            str(itcm_bin),
        ]
    )
    _write_byte_hex(itcm_bin, itcm_hex)
    try:
        _run(
            [
                _tool("objcopy"),
                "-O",
                "binary",
                "--only-section=.data",
                str(elf),
                str(dtcm_bin),
            ]
        )
    except subprocess.CalledProcessError:
        dtcm_bin.write_bytes(b"")
    _write_byte_hex(dtcm_bin, dtcm_hex)
    with symbols.open("w", encoding="utf-8") as stream:
        subprocess.run([_tool("nm"), "-n", str(elf)], check=True, stdout=stream)
    return itcm_hex, dtcm_hex, symbols


def build_sep_boot_rom() -> Path:
    output_dir = BUILD_ROOT / "boot_rom"
    elf = output_dir / "smu_sep_boot_rom.elf"
    binary = output_dir / "smu_sep_boot_rom.bin"
    rom_hex = output_dir / "smu_sep_boot_rom.hex"
    _compile(
        arch="rv32imc_zicsr_zifencei",
        abi="ilp32",
        linker=COMMON / "sep_boot_rom.ld",
        sources=[COMMON / "sep_boot_rom.S"],
        output=elf,
    )
    _run([_tool("objcopy"), "-O", "binary", str(elf), str(binary)])
    _write_word64_hex(binary, rom_hex)
    return rom_hex


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("preloads", "smu_smc_smoke", "smu_sep_smoke", "all"),
        required=True,
    )
    args = parser.parse_args()
    gen_preloads()
    if args.target in ("smu_smc_smoke", "all"):
        build_smc_rom("smu_smc_smoke")
    if args.target in ("smu_sep_smoke", "all"):
        build_smc_rom("smu_sep_arm")
        build_sep_firmware()
        build_sep_boot_rom()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
