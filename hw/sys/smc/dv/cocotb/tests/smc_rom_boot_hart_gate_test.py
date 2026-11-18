# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Only the boot hart runs the target ROM's early memory-health checks.

boot-flow.adoc, "Assembly early boot": the boot hart calls __metal_mbist_early_check and
__metal_memory_repair_check; every hart establishes gp, installs early_trap_vector in mtvec
and enters the C runtime, where the other harts end in the secondary_main wfi loop.

From the target's release until the controller's OCCP exchange completes, the retirement
records of all four target harts are sampled on every clk_smc_i cycle, and the run requires:

    harts 1-3  never retire inside either check function
    harts 1-3  each retire the _enter csrw that installs early_trap_vector, and retire inside
               secondary_main
    hart 0     retires inside both check functions

A function's extent is [its label, the next symbol) in the staged prod_rom.sym, which covers
the entry prologue every call executes. The csrw address comes from the staged prod_rom.dis.
The DFT status lines stay at their passing posture, so hart 0 runs both checks to completion.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      occp_sanity controller image        (required)
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test
from smc_occp_dual_defs import required_plusarg, rom_symbol_ranges
from smc_occp_rom_only_test import run_occp_rom_only

CASE = "smc_rom_boot_hart_gate_test"
CHECK_FUNCTIONS = ("__metal_mbist_early_check", "__metal_memory_repair_check")
SECONDARY_LOOP = "secondary_main"
ENTRY = "_enter"
TRAP_VECTOR = "early_trap_vector"
HARTS = (0, 1, 2, 3)
REQUIRED_EVIDENCE = (
    "CHK-OCCP-SANITY",
    "CHK-ROM-BOOT-HART-GATE",
    "CHK-ROM-SECONDARY-EARLY-FLOW",
    "CHK-ROM-BOOT-HART-CHECKS",
)

# One `objdump -d` instruction line: "<addr>:\t<encoding>\t<mnemonic>\t<operands>".
_DIS_LINE = re.compile(r"^\s*([0-9a-f]+):\s+[0-9a-f]+\s+(\S+)\s*(.*)$")


def _trap_vector_install_pc(entry: tuple[int, int]) -> int:
    """Address of the _enter `csrw mtvec,t0` that follows the load of early_trap_vector."""
    rom = required_plusarg("rom_bin64", CASE)
    dis = Path(Path(rom).name.removesuffix(".bin64") + ".dis")
    if not dis.exists():
        raise AssertionError(f"no staged disassembly {dis} for +rom_bin64={rom}")
    loaded = False
    found: list[int] = []
    for line in dis.read_text().splitlines():
        match = _DIS_LINE.match(line)
        if match is None:
            continue
        addr = int(match.group(1), 16)
        if not entry[0] <= addr < entry[1]:
            continue
        if f"<{TRAP_VECTOR}>" in match.group(3):
            loaded = True
        elif loaded and match.group(2) == "csrw" and match.group(3).startswith("mtvec,"):
            found.append(addr)
            loaded = False
    if len(found) != 1:
        raise AssertionError(
            f"{dis}: expected one csrw mtvec after the load of {TRAP_VECTOR} in {ENTRY}, "
            f"found {[f'{a:#x}' for a in found]}"
        )
    return found[0]


class _HartRetirements:
    """Distinct retired PCs per target hart, sampled on every clk_smc_i edge."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.signals = {
            0: (dut.dut_cpu_trace_valid, dut.dut_cpu_trace_exc, dut.dut_cpu_trace_pc),
            **{
                hart: (
                    getattr(dut, f"dut_hart{hart}_trace_valid"),
                    getattr(dut, f"dut_hart{hart}_trace_exc"),
                    getattr(dut, f"dut_hart{hart}_trace_pc"),
                )
                for hart in HARTS[1:]
            },
        }
        self.retired: dict[int, set[int]] = {hart: set() for hart in HARTS}
        self.trapped: dict[int, set[int]] = {hart: set() for hart in HARTS}
        self.running = True

    async def run(self) -> None:
        while self.running:
            await RisingEdge(self.dut.clk_smc_i)
            for hart, (valid, exc, pc) in self.signals.items():
                if not (valid.value.is_resolvable and int(valid.value)):
                    continue
                if not (exc.value.is_resolvable and pc.value.is_resolvable):
                    raise AssertionError(
                        f"target hart {hart} retired with an unresolved exception flag or PC"
                    )
                target = self.trapped if int(exc.value) else self.retired
                target[hart].add(int(pc.value))

    def seen(self, hart: int) -> set[int]:
        return self.retired[hart] | self.trapped[hart]


def _inside(pcs: set[int], extent: tuple[int, int]) -> list[int]:
    return sorted(pc for pc in pcs if extent[0] <= pc < extent[1])


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_boot_hart_gate_test(harness: SmcDualHarness) -> None:
    dut = harness.dut
    ranges = rom_symbol_ranges((*CHECK_FUNCTIONS, SECONDARY_LOOP, ENTRY))
    mtvec_pc = _trap_vector_install_pc(ranges[ENTRY])
    harts = _HartRetirements(dut)

    async def start_sampling(_dut_csr: DualCsr, _bfm_csr: DualCsr) -> None:
        cocotb.start_soon(harts.run())

    await run_occp_rom_only(harness, case=CASE, before_release=start_sampling)
    harts.running = False

    def describe(name: str) -> str:
        lo, hi = ranges[name]
        return f"{name} [{lo:#x}, {hi:#x})"

    for hart in HARTS[1:]:
        for name in CHECK_FUNCTIONS:
            inside = _inside(harts.seen(hart), ranges[name])
            if inside:
                raise AssertionError(
                    f"target hart {hart} retired {[f'{pc:#x}' for pc in inside]} inside "
                    f"{describe(name)}; only the boot hart runs the early memory checks"
                )
    cocotb.log.info(
        "CHK-ROM-BOOT-HART-GATE: target harts 1-3 retired %s distinct PCs, none inside %s",
        "/".join(str(len(harts.seen(hart))) for hart in HARTS[1:]),
        " or ".join(describe(name) for name in CHECK_FUNCTIONS),
    )

    for hart in HARTS[1:]:
        if mtvec_pc not in harts.retired[hart]:
            raise AssertionError(
                f"target hart {hart} never retired the {ENTRY} csrw mtvec at {mtvec_pc:#x} "
                f"that installs {TRAP_VECTOR}"
            )
        if not _inside(harts.retired[hart], ranges[SECONDARY_LOOP]):
            raise AssertionError(
                f"target hart {hart} never retired inside {describe(SECONDARY_LOOP)}"
            )
    cocotb.log.info(
        "CHK-ROM-SECONDARY-EARLY-FLOW: target harts 1-3 each retired the %s csrw mtvec at "
        "%#x and retired inside %s",
        TRAP_VECTOR,
        mtvec_pc,
        describe(SECONDARY_LOOP),
    )

    for name in CHECK_FUNCTIONS:
        if not _inside(harts.seen(0), ranges[name]):
            raise AssertionError(
                f"target hart 0 never retired inside {describe(name)}; the boot hart skipped "
                "the check"
            )
    cocotb.log.info(
        "CHK-ROM-BOOT-HART-CHECKS: target hart 0 retired inside %s",
        " and ".join(
            f"{describe(name)} at {[f'{pc:#x}' for pc in _inside(harts.seen(0), ranges[name])]}"
            for name in CHECK_FUNCTIONS
        ),
    )
    cocotb.log.info("%s PASS", CASE)
