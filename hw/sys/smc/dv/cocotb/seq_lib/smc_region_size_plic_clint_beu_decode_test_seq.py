# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PLIC, CLINT and the four bus-error units decode once REGION_SIZE covers them.

``memmap.adoc`` (SMC Address Space Layout, SMC Component Address Map) and
``interrupts.adoc`` (Interrupt Controller Address Map) place the PLIC at
``BASE + 0x400_0000``, the CLINT at ``BASE + 0x800_0000`` and the four
bus-error units at ``BASE + 0x801_0000 + N * 0x1000``, and ``fabric.adoc``
(Local and Remote Resource Access) sizes both the local and the global
aperture with the ``REGION_SIZE`` CSR, whose reset is 16 MiB.

At the 16 MiB reset the PLIC, CLINT and BEU addresses lie outside the local
aperture, and neither ``fabric.adoc`` nor ``memmap.adoc`` says what an inbound
access above the aperture returns; this sequence reads the PLIC priority word
at the reset size with the response tolerated and reports what came back,
without comparing it. It then programs ``REGION_SIZE`` to 256 MiB, the
smallest power of two that contains the whole documented map up to
``BASE + 0x801_3FFF``, and drives the three windows -- their co-resident
patterns and generated resets are what prove the aperture widened:

* PLIC: priority and per-core enable words hold distinct co-resident patterns,
  are then written to the priority-0 / disabled state ``interrupts.adoc``
  requires of firmware and read back; the top word of the 4 MiB window and the
  first word above it must answer without returning either pattern.
* CLINT: ``MSIP_0`` and ``MTIMECMP_0`` hold distinct co-resident patterns; the
  top word of the 64 KiB window must not return them.
* BEU: the four ``ENABLE`` registers read their generated reset and then hold
  four distinct co-resident patterns, so the per-core instances are proven
  separate rather than one aliased register.

``REGION_SIZE`` is restored to its generated reset and a local-window register
is read afterwards, so the aperture is left as the rest of the suite expects.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import (
    _REPO,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import WDT_CMP_REG_DEFAULT  # noqa: E402

_BEU_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "bus_error_unit.h"
BEU_ENABLE_RESET = reg_reset_word(_BEU_H, "BUS_ERROR_UNIT", "ENABLE")

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
# fabric.adoc: REGION_SIZE is a power of two by software contract. 256 MiB is
# the smallest one whose aperture reaches the last address memmap.adoc lists
# (the top of the timer / bus-error region at BASE + 0x801_3FFF).
REGION_SIZE_256M = 0x1000_0000
LOCAL_BASE = LOCAL_BASE_RESET
SPEC_MAP_TOP_OFFSET = 0x0801_3FFF
assert REGION_SIZE_256M > SPEC_MAP_TOP_OFFSET
assert REGION_SIZE_RESET <= SPEC_MAP_TOP_OFFSET

WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
WDT_CMP_WINDOW_OFFSET = WDT0_CMP - LOCAL_BASE

# --- PLIC: 4 MiB window; priority words from +0x0, core 0 MEIP enables +0x2000 ---
PLIC_BASE = smc_addr("SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR")
PLIC_PRIORITY_1 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY_BASE_ADDR", 1)
PLIC_CORE0_ENABLE_0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_PLIC_CORE0_MEIP_ENABLE_BASE_ADDR", 0)
# memmap.adoc / interrupts.adoc: PLIC = BASE + 0x400_0000 - BASE + 0x43F_FFFF.
PLIC_SPEC_TOP = LOCAL_BASE + 0x043F_FFF8
PLIC_SPEC_ABOVE = LOCAL_BASE + 0x0440_0000
# The PLIC word at the watchdog CMP's window offset: read at the reset aperture
# with the response tolerated (the specification does not define it) and again
# once the aperture covers the PLIC.
PLIC_WORD_AT_WDT_CMP_OFFSET = PLIC_BASE + WDT_CMP_WINDOW_OFFSET
# plic.h: PRIORITY.VALUE is 3 bits, so the pattern has to fit in it.
_PRIORITY_PATTERN = 0x5
_ENABLE_PATTERN = 0xA5A5_5A5A
PLIC_PRIORITY_ZERO = 0x0
PLIC_ENABLE_DISABLED = 0x0

# --- CLINT: 64 KiB window; MSIP words from +0x0, MTIMECMP from +0x4000 ---
CLINT_MSIP_0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", 0)
CLINT_MTIMECMP_0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIMECMP_BASE_ADDR", 0)
CLINT_SPEC_TOP = LOCAL_BASE + 0x0800_FFF8
# clint.h: MSIP.VALUE is 1 bit; MTIMECMP.COUNT is 64.
_MSIP_PATTERN = 0x1
_MTIMECMP_PATTERN = 0x0000_0FFF_FFFF_FF01
_MTIMECMP_RESTORE = 0xFFFF_FFFF_FFFF_FFFF

# --- BEU: four 4 KiB instances at BASE + 0x801_0000 + N * 0x1000 --------------
BEU_ENABLE = tuple(
    smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_BEU_ENABLE_BASE_ADDR") for core in range(4)
)
BEU0_CAUSE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_BEU_CAUSE_BASE_ADDR")
BEU_SPEC_STRIDE = 0x1000
# bus_error_unit.h: ENABLE has six implemented bits below 0x100, so the four
# patterns are distinct inside the writable mask.
_BEU_PATTERNS = (0x02, 0x04, 0x20, 0x40)

TIMER_BUSERROR_SPEC_TOP = LOCAL_BASE + 0x0801_3FF8

EXPECTED_ACCESSES = 53
EXPECTED_VALUE_CHECKS = 27


class smc_region_size_plic_clint_beu_decode_test_seq(SmcDecodeProbeSeq):
    """REGION_SIZE at reset, then PLIC / CLINT / BEU decode at 256 MiB."""

    def __init__(self, name: str = "smc_region_size_plic_clint_beu_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0
        # What the PLIC word answered at the reset aperture: (resp, rdata),
        # reported and not compared -- the specification leaves it undefined.
        self.above_aperture_at_reset: tuple[int, int] | None = None
        self.plic_word_at_256m: int | None = None

    async def _reset_region_size(self) -> None:
        """REGION_SIZE reads its generated reset; the local window answers below it."""
        await self.read_reset("REGION_SIZE_AT_RESET", REGION_SIZE, REGION_SIZE_RESET)
        await self.read_reset("WDT0_CMP_LOCAL", WDT0_CMP, WDT_CMP_REG_DEFAULT)
        self.above_aperture_at_reset = await self.read_any(
            "PLIC_WORD_ABOVE_RESET_APERTURE", PLIC_WORD_AT_WDT_CMP_OFFSET
        )
        resp, rdata = self.above_aperture_at_reset
        self.close_cell(
            "region-size-reset-16mib",
            f"REGION_SIZE read its generated reset {REGION_SIZE_RESET:#x} and WDT0 CMP inside "
            f"that aperture read its generated reset 0x{WDT_CMP_REG_DEFAULT:x}; "
            f"0x{PLIC_WORD_AT_WDT_CMP_OFFSET:08x}, above the aperture, answered resp={resp} "
            f"rdata=0x{rdata:x}, which fabric.adoc leaves undefined and this leg reports "
            f"without comparing",
        )

    async def _widen_region_size(self) -> None:
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        # The same PLIC word, now inside the aperture, answers OKAY (the
        # scoreboard requires it); its value is reported here and the PLIC
        # co-resident patterns below are the proof that the aperture widened.
        self.plic_word_at_256m = await self.csr_read(
            "PLIC_WORD_INSIDE_256M", PLIC_WORD_AT_WDT_CMP_OFFSET
        )

    async def _plic(self) -> None:
        await self.rw_coresident(
            [
                ("PLIC_PRIORITY_1", PLIC_PRIORITY_1, _PRIORITY_PATTERN, PLIC_PRIORITY_ZERO),
                ("PLIC_CORE0_ENABLE_0", PLIC_CORE0_ENABLE_0, _ENABLE_PATTERN, PLIC_ENABLE_DISABLED),
            ]
        )
        self.close_cell(
            "plic-region",
            f"PRIORITY[1] @0x{PLIC_PRIORITY_1:08x} and CORE0_MEIP_ENABLE[0] "
            f"@0x{PLIC_CORE0_ENABLE_0:08x} held distinct co-resident patterns "
            f"({_PRIORITY_PATTERN:#x}, {_ENABLE_PATTERN:#x})",
        )
        self.close_cell(
            "plic-base-access",
            f"PRIORITY[1] @0x{PLIC_PRIORITY_1:08x}, the second word of the PLIC window at "
            f"0x{PLIC_BASE:08x}, held and returned {_PRIORITY_PATTERN:#x}",
        )
        self.close_cell(
            "priority-written-to-zero",
            f"PRIORITY[1] restored to {PLIC_PRIORITY_ZERO:#x} and read back exactly",
        )
        self.close_cell(
            "enables-written-to-disabled",
            f"CORE0_MEIP_ENABLE[0] restored to {PLIC_ENABLE_DISABLED:#x} and read back exactly",
        )
        self.close_cell(
            "readback-matches",
            f"both PLIC words read back the priority-0 / disabled state written to them, after "
            f"having held {_PRIORITY_PATTERN:#x} / {_ENABLE_PATTERN:#x}",
        )

    async def _plic_edges(self) -> None:
        # With a pattern resident in the PLIC, an address outside the block that
        # returned it would be an alias. Re-arm the pattern for the edge probes
        # and restore it afterwards.
        await self.csr_write("PLIC_PRIORITY_1_EDGE_ARM", PLIC_PRIORITY_1, _PRIORITY_PATTERN)
        await self.csr_read(
            "PLIC_PRIORITY_1_EDGE_ARM_RB", PLIC_PRIORITY_1, expected=_PRIORITY_PATTERN
        )
        top = await self.csr_read("PLIC_SPEC_TOP", PLIC_SPEC_TOP, length=8)
        assert top != _PRIORITY_PATTERN, (
            f"0x{PLIC_SPEC_TOP:08x}, the top word of the 4 MiB PLIC window, returned the "
            f"priority pattern {_PRIORITY_PATTERN:#x}: the window aliases onto the priority array"
        )
        above = await self.csr_read("PLIC_SPEC_ABOVE", PLIC_SPEC_ABOVE, length=8)
        assert above != _PRIORITY_PATTERN, (
            f"0x{PLIC_SPEC_ABOVE:08x}, the first word above the PLIC window, returned the "
            f"priority pattern {_PRIORITY_PATTERN:#x}: it is answered by the PLIC"
        )
        await self.csr_write("PLIC_PRIORITY_1_RESTORE", PLIC_PRIORITY_1, PLIC_PRIORITY_ZERO)
        await self.csr_read(
            "PLIC_PRIORITY_1_RESTORE_RB", PLIC_PRIORITY_1, expected=PLIC_PRIORITY_ZERO
        )
        self.close_cell(
            "plic-top-access",
            f"0x{PLIC_SPEC_TOP:08x} (last word of the 4 MiB window) answered with 0x{top:x}, not "
            f"the resident priority pattern {_PRIORITY_PATTERN:#x}",
        )
        self.close_cell(
            "just-above-plic-not-plic",
            f"0x{PLIC_SPEC_ABOVE:08x} (first word above the window) answered with 0x{above:x}, not "
            f"the resident priority pattern {_PRIORITY_PATTERN:#x}",
        )

    async def _clint(self) -> None:
        # Both patterns are resident before either is read back, so a decode
        # that folds MTIMECMP_0 onto MSIP_0 (or the reverse) fails the first
        # readback; the two registers differ in width, so the legs are spelt out.
        await self.csr_write("CLINT_MSIP_0_PATTERN", CLINT_MSIP_0, _MSIP_PATTERN)
        await self.csr_write("CLINT_MTIMECMP_0", CLINT_MTIMECMP_0, _MTIMECMP_PATTERN, length=8)
        await self.csr_read("CLINT_MSIP_0_PATTERN_RB", CLINT_MSIP_0, expected=_MSIP_PATTERN)
        await self.csr_read(
            "CLINT_MTIMECMP_0_RB", CLINT_MTIMECMP_0, expected=_MTIMECMP_PATTERN, length=8
        )
        await self.csr_write("CLINT_MSIP_0_RESTORE", CLINT_MSIP_0, 0)
        await self.csr_read("CLINT_MSIP_0_RESTORE_RB", CLINT_MSIP_0, expected=0)
        top = await self.csr_read("CLINT_SPEC_TOP", CLINT_SPEC_TOP, length=8)
        assert top != _MTIMECMP_PATTERN, (
            f"0x{CLINT_SPEC_TOP:08x}, the top word of the 64 KiB CLINT window, returned the "
            f"resident MTIMECMP pattern: the window aliases onto MTIMECMP_0"
        )
        cause = await self.read_reset("BEU0_CAUSE", BEU0_CAUSE, 0, length=8)
        await self.csr_write(
            "CLINT_MTIMECMP_0_RESTORE", CLINT_MTIMECMP_0, _MTIMECMP_RESTORE, length=8
        )
        self.close_cell(
            "clint-base-access",
            f"MSIP_0 @0x{CLINT_MSIP_0:08x} (first word of the CLINT window) held and returned "
            f"{_MSIP_PATTERN:#x} while MTIMECMP_0 held {_MTIMECMP_PATTERN:#x}, and was restored "
            f"to 0",
        )
        self.close_cell(
            "clint-top-access",
            f"0x{CLINT_SPEC_TOP:08x} (last word of the 64 KiB window) answered with 0x{top:x}, not "
            f"the resident MTIMECMP pattern 0x{_MTIMECMP_PATTERN:x}",
        )
        self.close_cell(
            "just-above-clint-not-clint",
            f"0x{BEU0_CAUSE:08x}, the first word above the CLINT window, is the core 0 BEU CAUSE "
            f"and read 0x{cause:x}, not the resident MTIMECMP pattern",
        )

    async def _beu(self) -> None:
        for core, addr in enumerate(BEU_ENABLE):
            await self.read_reset(f"BEU{core}_ENABLE_RESET", addr, BEU_ENABLE_RESET)
            assert addr == BEU_ENABLE[0] + core * BEU_SPEC_STRIDE, (
                f"core {core} BEU ENABLE is at 0x{addr:08x}, not the spec stride "
                f"0x{BEU_SPEC_STRIDE:x} from 0x{BEU_ENABLE[0]:08x}"
            )
        await self.rw_coresident(
            [
                (f"BEU{core}_ENABLE", addr, _BEU_PATTERNS[core], BEU_ENABLE_RESET)
                for core, addr in enumerate(BEU_ENABLE)
            ]
        )
        for core in range(4):
            self.close_cell(
                f"beu{core}-decode",
                f"core {core} BEU ENABLE @0x{BEU_ENABLE[core]:08x} read the generated reset "
                f"0x{BEU_ENABLE_RESET:x} and then held pattern {_BEU_PATTERNS[core]:#x} while the "
                f"other three held theirs",
            )
        self.close_cell(
            "beu-instance-3",
            f"core 3 BEU ENABLE @0x{BEU_ENABLE[3]:08x} == 0x{BEU_ENABLE[0]:08x} + 3 * "
            f"0x{BEU_SPEC_STRIDE:x} held {_BEU_PATTERNS[3]:#x} co-resident with cores 0-2",
        )
        top = await self.csr_read("TIMER_BUSERROR_SPEC_TOP", TIMER_BUSERROR_SPEC_TOP, length=8)
        self.close_cell(
            "timer-buserror-region",
            f"the 80 KiB region answered at its CLINT base 0x{CLINT_MSIP_0:08x}, at all four BEU "
            f"instances and at its top word 0x{TIMER_BUSERROR_SPEC_TOP:08x} (0x{top:x})",
        )

    async def _restore_region_size(self) -> None:
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
        await self.read_reset("WDT0_CMP_AFTER_RESTORE", WDT0_CMP, WDT_CMP_REG_DEFAULT)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen

        await self._reset_region_size()
        await self._widen_region_size()
        await self._plic()
        await self._plic_edges()
        await self._clint()
        await self._beu()
        await self._restore_region_size()

        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks_measured} exact-value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        self.report_cells("CHK-REGION-SIZE-PLIC-CLINT-BEU")
        cocotb.log.info(
            "CHK-REGION-SIZE-PLIC-CLINT-BEU-DECODE: at REGION_SIZE 0x%x the PLIC word above the "
            "aperture answered resp=%d rdata=0x%x (reported, not compared); at 0x%x the same "
            "address answered OKAY with 0x%x and the PLIC, CLINT and four BEU windows held their "
            "co-resident patterns; %d cells closed over %d accesses with %d scoreboard "
            "exact-value compares (floor %d)",
            REGION_SIZE_RESET,
            self.above_aperture_at_reset[0],
            self.above_aperture_at_reset[1],
            REGION_SIZE_256M,
            self.plic_word_at_256m,
            len(self.cells),
            self.accesses,
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
        )
