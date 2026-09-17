# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Local alias base, the eight alias-remap regions, the spare blocks and both mailbox halves.

Four groups that share one setup -- SEP_IN CSR traffic into the local window
with nothing else configured:

* ``fabric.adoc`` (Local and Remote Resource Access) makes ``LOCAL_BASE`` a
  fixed read-only alias of the SMC's own resources, and ``memmap.adoc`` (SMC
  Component Address Map) puts the core-0 watchdog at window offset 0. The first
  access of the sequence is therefore a read at ``LOCAL_BASE`` itself, taken
  before anything is written to the remap block, so it is also the evidence
  that remap is transparent at its reset setting. ``CMP`` in the same block
  carries a non-zero generated reset, which is what makes the ``CTRL`` read at
  offset 0 decode evidence rather than a 0 == 0 compare.
* ``memmap.adoc``: "Alias Remap | BASE + 0x001_2000 + (N x 0x20) | 8 instances".
  Regions 0 and 7 -- the ends of the array -- are configured with distinct
  co-resident ``REGION_START`` values and restored to the generated reset, so a
  decoder that collapses the eight instances onto one fails the readback.
* ``memmap.adoc`` (Spare SMC Register Blocks): the scratch block holds an
  all-ones word and reads it back, and the chip-config block is written and
  must still read its generated reset, because every ``chip_config.rdl`` field
  is ``sw = r``.
* ``memmap.adoc``: "Mailbox | BASE + 0x001_8000 - BASE + 0x003_7FFF | 32 pairs
  | (32 inbound + 32 outbound)". The offset of each half inside a pair comes
  from the generated map; all four end instances hold distinct co-resident
  patterns at once.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_decode_probe_utils import SmcDecodeProbeSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    CHIP_CONFIG_CHIP_ID_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    SCRATCH_SCRATCH_REG_DEFAULT,
    WDT_CMP_REG_DEFAULT,
    WDT_CTRL_REG_DEFAULT,
)

LOCAL_BASE = 0xC000_0000

# --- local alias base: the core-0 watchdog sits at window offset 0 ------------
WDT0_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
assert WDT0_CTRL == LOCAL_BASE

# --- alias remap: 8 regions, 0x20 apart --------------------------------------
ALIAS_NUM = smc_addr("SMC_TOP_SMC_ALIAS_REMAP_NUM")
ALIAS_SPEC_STRIDE = 0x20
ALIAS_REGION_START = tuple(
    smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", region)
    for region in range(ALIAS_NUM)
)
assert ALIAS_REGION_START[0] == LOCAL_BASE + 0x0001_2000
_ALIAS_PATTERN_0 = 0x0000_0000_4000_0000
_ALIAS_PATTERN_7 = 0x0000_0000_5000_0000

# --- spare blocks ------------------------------------------------------------
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
CHIP_CONFIG_CHIP_ID = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR")
_SCRATCH_ALL_ONES = 0xFFFF_FFFF
_CHIP_ID_WRITE = 0xA5A5_5A5A

# --- mailbox: the two halves of pair 0 and pair 31 ---------------------------
MBX_OUT0_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
MBX_IN0_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
MBX_OUT31_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_31_IRQEN_BASE_ADDR")
MBX_IN31_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_IRQEN_BASE_ADDR")
# IRQEN has three bits of real storage (wtirq, rtirq, eirq); these are the four
# distinct non-zero patterns that fit and differ from the reset 0.
_MBX_PATTERNS = (0x1, 0x2, 0x4, 0x3)

EXPECTED_ACCESSES = 33
EXPECTED_VALUE_CHECKS = 18


class smc_alias_remap_spare_block_decode_test_seq(SmcDecodeProbeSeq):
    """Local alias base, alias-remap ends, spare blocks and both mailbox halves."""

    def __init__(self, name: str = "smc_alias_remap_spare_block_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0

    async def _local_alias_base(self) -> None:
        # First access of the run, and before anything is written to the remap
        # block: whatever answers here does so through the transparent reset
        # setting of the alias remap.
        await self.read_reset("LOCAL_BASE_WDT0_CTRL", WDT0_CTRL, WDT_CTRL_REG_DEFAULT)
        await self.read_reset("LOCAL_BASE_WDT0_CMP", WDT0_CMP, WDT_CMP_REG_DEFAULT)
        self.close_cell(
            "local-alias-base-reaches-local-resource",
            f"0x{WDT0_CTRL:08x} (LOCAL_BASE itself) read the core-0 watchdog CTRL reset "
            f"0x{WDT_CTRL_REG_DEFAULT:x} and CMP at +0x{WDT0_CMP - WDT0_CTRL:x} in the same block "
            f"read its non-zero reset 0x{WDT_CMP_REG_DEFAULT:x}, so the watchdog answered",
        )
        self.close_cell(
            "transparent-at-reset",
            f"the LOCAL_BASE read above was the first access of the run and no alias-remap region "
            f"had been written, so 0x{WDT0_CTRL:08x} reached the local resource through the reset "
            f"remap configuration",
        )

    async def _alias_regions(self) -> None:
        for region in range(ALIAS_NUM):
            assert ALIAS_REGION_START[region] == ALIAS_REGION_START[0] + region * ALIAS_SPEC_STRIDE
        await self.rw_coresident(
            [
                (
                    "ALIAS_REGION_0_START",
                    ALIAS_REGION_START[0],
                    _ALIAS_PATTERN_0,
                    REMAP_REGION_REGION_START_REG_DEFAULT,
                ),
                (
                    f"ALIAS_REGION_{ALIAS_NUM - 1}_START",
                    ALIAS_REGION_START[ALIAS_NUM - 1],
                    _ALIAS_PATTERN_7,
                    REMAP_REGION_REGION_START_REG_DEFAULT,
                ),
            ],
            length=8,
        )
        self.close_cell(
            "alias-region-0-configured",
            f"REGION_START of alias region 0 @0x{ALIAS_REGION_START[0]:08x} held "
            f"0x{_ALIAS_PATTERN_0:x} while region {ALIAS_NUM - 1} held 0x{_ALIAS_PATTERN_7:x}, then "
            f"read back the generated reset 0x{REMAP_REGION_REGION_START_REG_DEFAULT:x}",
        )
        self.close_cell(
            "alias-region-7-configured",
            f"REGION_START of alias region {ALIAS_NUM - 1} "
            f"@0x{ALIAS_REGION_START[ALIAS_NUM - 1]:08x} == 0x{ALIAS_REGION_START[0]:08x} + "
            f"{ALIAS_NUM - 1} * 0x{ALIAS_SPEC_STRIDE:x} held 0x{_ALIAS_PATTERN_7:x} co-resident "
            f"with region 0 and was restored",
        )

    async def _spare_blocks(self) -> None:
        await self.csr_write("SCRATCH_COLD_0_ALL_ONES", SCRATCH_COLD_0, _SCRATCH_ALL_ONES)
        await self.csr_read(
            "SCRATCH_COLD_0_ALL_ONES_RB", SCRATCH_COLD_0, expected=_SCRATCH_ALL_ONES
        )
        await self.csr_write("SCRATCH_COLD_0_RESTORE", SCRATCH_COLD_0, SCRATCH_SCRATCH_REG_DEFAULT)
        await self.csr_read(
            "SCRATCH_COLD_0_RESTORE_RB", SCRATCH_COLD_0, expected=SCRATCH_SCRATCH_REG_DEFAULT
        )
        self.close_cell(
            "scratch-all-ones",
            f"SCRATCH_COLD[0] @0x{SCRATCH_COLD_0:08x} held 0x{_SCRATCH_ALL_ONES:08x} and read it "
            f"back exactly, so all 32 bits of the spare scratch word are storage",
        )
        # chip_config.rdl declares every field `sw = r`, so the write must be
        # accepted by the block and must not change the value.
        await self.read_reset(
            "CHIP_CONFIG_CHIP_ID_BEFORE", CHIP_CONFIG_CHIP_ID, CHIP_CONFIG_CHIP_ID_REG_DEFAULT
        )
        await self.csr_write("CHIP_CONFIG_CHIP_ID_WRITE", CHIP_CONFIG_CHIP_ID, _CHIP_ID_WRITE)
        await self.read_reset(
            "CHIP_CONFIG_CHIP_ID_AFTER", CHIP_CONFIG_CHIP_ID, CHIP_CONFIG_CHIP_ID_REG_DEFAULT
        )
        self.close_cell(
            "chip-config-write",
            f"a write of 0x{_CHIP_ID_WRITE:08x} to CHIP_ID @0x{CHIP_CONFIG_CHIP_ID:08x} was "
            f"accepted by the chip-config block and the register still read its generated reset "
            f"0x{CHIP_CONFIG_CHIP_ID_REG_DEFAULT:x}, which is what `sw = r` on every field means "
            f"at this boundary",
        )

    async def _mailbox_halves(self) -> None:
        entries = [
            ("MBX_OUTBOUND_0_IRQEN", MBX_OUT0_IRQEN, _MBX_PATTERNS[0], 0),
            ("MBX_INBOUND_0_IRQEN", MBX_IN0_IRQEN, _MBX_PATTERNS[1], 0),
            ("MBX_OUTBOUND_31_IRQEN", MBX_OUT31_IRQEN, _MBX_PATTERNS[2], 0),
            ("MBX_INBOUND_31_IRQEN", MBX_IN31_IRQEN, _MBX_PATTERNS[3], 0),
        ]
        await self.rw_coresident(entries)
        for cell, (_label, addr, pattern, _restore) in zip(
            ("outbound-pair-0", "inbound-pair-0", "outbound-pair-31", "inbound-pair-31"),
            entries,
            strict=True,
        ):
            self.close_cell(
                cell,
                f"IRQEN @0x{addr:08x} held pattern {pattern:#x} while the other three halves held "
                f"theirs, then read back 0",
            )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen

        await self._local_alias_base()
        await self._alias_regions()
        await self._spare_blocks()
        await self._mailbox_halves()

        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks_measured} exact-value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        self.report_cells("CHK-ALIAS-REMAP-SPARE-BLOCK")
        cocotb.log.info(
            "CHK-ALIAS-REMAP-SPARE-BLOCK-DECODE: %d cells closed over %d accesses with %d "
            "scoreboard exact-value compares (floor %d): LOCAL_BASE read before any remap write, "
            "alias regions 0 and %d co-resident, the scratch and chip-config spare blocks, and "
            "all four end mailbox halves",
            len(self.cells),
            self.accesses,
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
            ALIAS_NUM - 1,
        )
