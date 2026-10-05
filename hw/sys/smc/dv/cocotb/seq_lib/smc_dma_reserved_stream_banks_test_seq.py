# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""All sixteen DMA stream banks decode with ``NUM_CTRL_STREAMS = 1``.

``dma.adoc`` (Stream Support) pins the behaviour: the register file is
generated with all 16 banks and every bank decodes normally regardless of the
stream-count parameter; ``STATUS_1..15`` and ``DONE_1..15`` are tied to 0, and
a read of ``NEXT_ID_1..15`` completes without a bus error, returns 0 and does
not start a transfer. ``NEXT_ID_0`` is the one register whose read launches a
transfer built from the shared descriptor registers, so it is not read here;
bank 0 is covered by ``STATUS_0`` and ``DONE_0``. The unused word at ``0x4C``
shares ``NEXT_ID_0``'s 8-byte word; a 32-bit read of it answers the hole
response the map gives (OKAY, ``0xFFFFFFFF``) and must not launch a transfer
either.

The zeros are given teeth two ways: ``DST_ADDRESS_LO`` in the same block takes
and returns a pattern first (so the block is answering, not a dead bus), and
``tb_dma_busy`` is sampled every ``clk_smc_i`` edge across the whole sweep and
must never rise (the reserved ``NEXT_ID`` reads and the ``0x4C`` read started
nothing).

Bank 0 is the functional stream: its ``STATUS_0`` and ``DONE_0`` are hardware
status the specification does not pin to a value, so they are read for an
OKAY response only and their values are reported, not compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import CLOCK_GATE_CONTROL, DMA_CG_EN, DMA_CTRL_BASE, dma_ctrl_offset
from .smc_decode_probe_utils import SmcDecodeProbeSeq

NUM_STREAM_BANKS = 16
DMA_DST_ADDRESS_LO = DMA_CTRL_BASE + dma_ctrl_offset("DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
_ALIVE_PATTERN = 0xA5A5_5A5A
_HOLE_RDATA = 0xFFFF_FFFF


def _bank_reg(name: str, bank: int) -> int:
    return DMA_CTRL_BASE + dma_ctrl_offset(f"DMA_CTRL_{name}_{bank}_BASE_ADDR")


# The other half of NEXT_ID_0's 8-byte word, which no register owns.
DMA_NEXT_ID_0_HOLE = _bank_reg("NEXT_ID", 0) + 4


# Reads carrying an exact expectation: 15 reserved STATUS + 15 reserved DONE +
# 15 reserved NEXT_ID + the NEXT_ID_0 hole + the two DST_ADDRESS_LO readbacks +
# the clock-gate restore readback.
EXPECTED_VALUE_CHECKS = 49
# Plus the two bank-0 reads, the clock-gate save read and three writes.
EXPECTED_ACCESSES = 56


class smc_dma_reserved_stream_banks_test_seq(SmcDecodeProbeSeq):
    """Sweep STATUS/DONE/NEXT_ID of every bank while watching for a launched transfer."""

    def __init__(self, name: str = "smc_dma_reserved_stream_banks_test_seq") -> None:
        super().__init__(name)
        self.busy_cycles = 0
        self.sampled_cycles = 0
        self.bank0_status: int | None = None
        self.bank0_done: int | None = None

    async def _watch_busy(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.sampled_cycles += 1
            value = dut.tb_dma_busy.value
            assert value.is_resolvable, f"tb_dma_busy is not resolvable: {value}"
            if int(value):
                self.busy_cycles += 1

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_dma_busy"), "tb_dma_busy probe missing"

        cg = await self.csr_read("DMA_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("DMA_UNGATE", CLOCK_GATE_CONTROL, cg & ~DMA_CG_EN)

        watcher = cocotb.start_soon(self._watch_busy())
        try:
            await self.csr_write("DMA_DST_ADDRESS_LO_ALIVE", DMA_DST_ADDRESS_LO, _ALIVE_PATTERN)
            await self.csr_read(
                "DMA_DST_ADDRESS_LO_ALIVE_RB", DMA_DST_ADDRESS_LO, expected=_ALIVE_PATTERN
            )

            self.bank0_status = await self.csr_read("DMA_STATUS_0", _bank_reg("STATUS", 0))
            self.bank0_done = await self.csr_read("DMA_DONE_0", _bank_reg("DONE", 0))
            for bank in range(1, NUM_STREAM_BANKS):
                await self.read_reset(f"DMA_STATUS_{bank}", _bank_reg("STATUS", bank), 0)
            for bank in range(1, NUM_STREAM_BANKS):
                await self.read_reset(f"DMA_DONE_{bank}", _bank_reg("DONE", bank), 0)
            for bank in range(1, NUM_STREAM_BANKS):
                await self.read_reset(f"DMA_NEXT_ID_{bank}", _bank_reg("NEXT_ID", bank), 0)
            await self.csr_read("DMA_NEXT_ID_0_HOLE", DMA_NEXT_ID_0_HOLE, expected=_HOLE_RDATA)

            await self.csr_write("DMA_DST_ADDRESS_LO_RESTORE", DMA_DST_ADDRESS_LO, 0)
            await self.csr_read("DMA_DST_ADDRESS_LO_RESTORE_RB", DMA_DST_ADDRESS_LO, expected=0)
        finally:
            watcher.cancel()

        await self.csr_write("DMA_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        await self.csr_read("DMA_CG_RESTORE_RB", CLOCK_GATE_CONTROL, expected=cg)

        assert self.sampled_cycles > 0, "the DMA busy watcher never sampled a clock edge"
        assert self.busy_cycles == 0, (
            f"tb_dma_busy rose for {self.busy_cycles} of {self.sampled_cycles} clk_smc_i cycles "
            f"during the reserved-bank sweep: a NEXT_ID_1..15 read or the 32-bit read of "
            f"0x{DMA_NEXT_ID_0_HOLE:08x} beside NEXT_ID_0 launched a transfer"
        )
        self.close_cell(
            "all-16-banks-decode",
            f"STATUS_1..15, DONE_1..15 and NEXT_ID_1..15 read 0 (all OKAY); the NEXT_ID_0 hole "
            f"read 0x{_HOLE_RDATA:08x}; bank 0 answered OKAY "
            f"with STATUS_0=0x{self.bank0_status:x} DONE_0=0x{self.bank0_done:x} (hardware status, "
            f"reported not compared); DST_ADDRESS_LO took 0x{_ALIVE_PATTERN:08x} in the same "
            f"block; tb_dma_busy stayed 0 for all {self.sampled_cycles} sampled cycles",
        )
        self.assert_all_reachable(EXPECTED_ACCESSES, "DMA_RESERVED_STREAM_BANKS")
        self.report_cells("CHK-DMA-STREAM-BANKS")
        cocotb.log.info(
            "CHK-DMA-RESERVED-STREAM-BANKS: %d banks decoded (STATUS, DONE, NEXT_ID_1..15) over "
            "%d SEP_IN accesses; tb_dma_busy high %d of %d cycles",
            NUM_STREAM_BANKS,
            self.accesses,
            self.busy_cycles,
            self.sampled_cycles,
        )
