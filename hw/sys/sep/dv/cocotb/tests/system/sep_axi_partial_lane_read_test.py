# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Partial-lane read determinism on the 64-bit CPU-LSU bus.

no_cpu / +skip_fuse_sense. A read narrower than the bus beat only obligates
the responder to drive the addressed byte lanes — a 32-bit CSR endpoint
leaves RDATA[63:32] undriven, a narrow-ARSIZE beat leaves every non-addressed
lane undriven — yet the value the VIP hands the test must be a pure function
of the addressed lanes. Complements ``sep_axi_strobe_window_test`` (write-side
lane masking): here the WRITE is trusted and the READ extraction is on trial.

Every read is compared against an independent golden AND repeated after a
disturbing read of an unrelated value, so a result that depends on undriven
lanes or leftover channel state fails as a mismatch rather than passing by
coincidence.

`[RANDCFG]` — ``SepAxiPartialLaneReadCfg`` owns stimulus + goldens. Required
cells run on every seed; the seed varies order, addresses, and data only.

  CHK-CSR-LANE   : 32-bit CSR (SW_DEBUG) write -> two 4-byte readbacks with a
                   checked RO-register disturb between them; both exact, both
                   identical. All-zeros and all-ones always run.
  CHK-SRAM-SLICE : all 36 contiguous (offset, length) byte-run reads of a
                   primed random 64-bit SRAM word; each read twice around a
                   checked complement-word disturb; exact slice golden.
  CHK-ARSIZE     : all 14 aligned narrow-ARSIZE cells (AxSIZE 0/1/2 at every
                   legal lane offset) on the same word; exact slice golden
                   and identical on re-read around a checked disturb.
  CHK-RANDCFG    : walked cell counts held against the 8-byte-beat floors
                   (36 slices, 14 ARSIZE cells); seed and resolved knobs logged.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_axi_partial_lane_read_seq import (
    ARSIZE_CELL_FLOOR,
    LOCAL_BASE_ADDR_ADDR,
    LOCAL_BASE_ADDR_EXP,
    SLICE_CELL_FLOOR,
    SW_DEBUG_ADDR,
    SepAxiPartialLaneRead,
    SepAxiPartialLaneReadCfg,
)


@pyuvm.test()
class sep_axi_partial_lane_read_test(sep_base_test):
    """Narrow-read lane extraction: exact goldens, repeatable around disturbs."""

    async def run_scenario(self) -> None:
        self.cfg_lane = SepAxiPartialLaneReadCfg(self.random_seed())
        self.logger.info("partial-lane config: %s", self.cfg_lane.summary())
        n_slice = len(self.cfg_lane.slice_specs)
        n_arsize = len(self.cfg_lane.arsize_specs)
        assert n_slice == SLICE_CELL_FLOOR, (
            f"CHK-RANDCFG FAIL: walked {n_slice} byte-run slices, want {SLICE_CELL_FLOOR}"
        )
        assert n_arsize == ARSIZE_CELL_FLOOR, (
            f"CHK-RANDCFG FAIL: walked {n_arsize} ARSIZE cells, want {ARSIZE_CELL_FLOOR}"
        )
        assert self.cfg_lane.csr_patterns[:2] == [0x0000_0000, 0xFFFF_FFFF], (
            "CHK-RANDCFG FAIL: all-zeros and all-ones CSR patterns not first"
        )
        self.logger.info(
            "CHK-RANDCFG PASS: seed=%d word=0x%016x @0x%08x slices=%d arsize=%d csr_patterns=%d",
            self.cfg_lane.seed,
            self.cfg_lane.word,
            self.cfg_lane.sram_addr,
            n_slice,
            n_arsize,
            len(self.cfg_lane.csr_patterns),
        )
        await self.bring_up_no_cpu()
        self.lane = SepAxiPartialLaneRead(self)
        await self._chk_csr_lane()
        await self._chk_sram_slice()
        await self._chk_arsize()
        self.logger.info(
            "partial-lane read PASS: CSR repeats, %d byte-run slices, and %d "
            "narrow-ARSIZE cells all exact and repeatable",
            n_slice,
            n_arsize,
        )

    async def _disturb_csr(self) -> None:
        """Checked disturbing read between repeats (RO register, known value)."""
        got = await self.lane.read(LOCAL_BASE_ADDR_ADDR, 4)
        assert got == LOCAL_BASE_ADDR_EXP, (
            f"disturb read LOCAL_BASE_ADDR 0x{got:08x} != 0x{LOCAL_BASE_ADDR_EXP:08x}"
        )

    async def _disturb_sram(self) -> None:
        """Checked disturbing read between repeats (complement neighbor word)."""
        cfg = self.cfg_lane
        got = await self.lane.read(cfg.disturb_addr, 8)
        assert got == cfg.disturb_word, (
            f"disturb read @0x{cfg.disturb_addr:08x} 0x{got:016x} != 0x{cfg.disturb_word:016x}"
        )

    async def _chk_csr_lane(self) -> None:
        """4-byte reads of a 32-bit CSR: only RDATA[31:0] is driven by the DUT."""
        for pattern in self.cfg_lane.csr_patterns:
            await self.lane.write(SW_DEBUG_ADDR, pattern, 4)
            first = await self.lane.read(SW_DEBUG_ADDR, 4)
            await self._disturb_csr()
            second = await self.lane.read(SW_DEBUG_ADDR, 4)
            assert first == pattern, f"CHK-CSR-LANE 0x{pattern:08x}: first read 0x{first:08x}"
            assert second == first, (
                f"CHK-CSR-LANE 0x{pattern:08x}: repeat 0x{second:08x} != "
                f"first 0x{first:08x} (read depends on leftover bus state)"
            )
        self.logger.info(
            "CHK-CSR-LANE PASS: %d patterns read back exact and repeatable "
            "through the half-driven CSR beat @0x%08x",
            len(self.cfg_lane.csr_patterns),
            SW_DEBUG_ADDR,
        )

    async def _chk_sram_slice(self) -> None:
        """Every contiguous byte-run slice of a primed word reads back exactly."""
        cfg = self.cfg_lane
        await self.lane.write(cfg.sram_addr, cfg.word, 8)
        await self.lane.write(cfg.disturb_addr, cfg.disturb_word, 8)
        for offset, length in cfg.slice_specs:
            exp = cfg.slice_golden(offset, length)
            first = await self.lane.read(cfg.sram_addr + offset, length)
            await self._disturb_sram()
            second = await self.lane.read(cfg.sram_addr + offset, length)
            assert first == exp, (
                f"CHK-SRAM-SLICE off {offset} len {length}: 0x{first:x} != "
                f"golden 0x{exp:x} (word 0x{cfg.word:016x})"
            )
            assert second == first, (
                f"CHK-SRAM-SLICE off {offset} len {length}: repeat 0x{second:x} "
                f"!= first 0x{first:x} (read depends on leftover bus state)"
            )
        self.logger.info(
            "CHK-SRAM-SLICE PASS: all %d byte-run slices of 0x%016x @0x%08x "
            "exact and repeatable around complement-word disturbs",
            len(cfg.slice_specs),
            cfg.word,
            cfg.sram_addr,
        )

    async def _chk_arsize(self) -> None:
        """Narrow-ARSIZE beats: only the addressed lanes are driven at all."""
        cfg = self.cfg_lane
        for size, offset in cfg.arsize_specs:
            length = 1 << size
            exp = cfg.slice_golden(offset, length)
            first = await self.lane.read(cfg.sram_addr + offset, length, size=size)
            await self._disturb_sram()
            second = await self.lane.read(cfg.sram_addr + offset, length, size=size)
            assert first == exp, (
                f"CHK-ARSIZE size {size} off {offset}: 0x{first:x} != golden "
                f"0x{exp:x} (word 0x{cfg.word:016x})"
            )
            assert second == first, (
                f"CHK-ARSIZE size {size} off {offset}: repeat 0x{second:x} "
                f"!= first 0x{first:x} (read depends on leftover bus state)"
            )
        self.logger.info(
            "CHK-ARSIZE PASS: all %d aligned AxSIZE-0/1/2 cells extracted the "
            "addressed lanes exactly and repeatably @0x%08x",
            len(cfg.arsize_specs),
            cfg.sram_addr,
        )
