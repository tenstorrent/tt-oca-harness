# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A partial write to an HMAC or Secure DMA register gets SLVERR and latches that block's bit.

sep_cpu_ctrl.rdl and hw/sys/sep/doc/interrupts.adoc require a write that the block's
register definition refuses to receive SLVERR and latch the owning block's bit: the
HMAC bit of PERIPH_BUS_ERR_STATUS for an HMAC register, and reg_path_err of
DMA_BUS_ERR_STATUS for a Secure DMA register. A partial write is one whose byte
strobe misses a byte that the register owns. A narrow read inside a register is a
legal access: it completes with OKAY and latches nothing.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import (
    DMA_REG_PATH_BIT,
    DMA_STATUS_ADDR,
    PERIPH_HMAC_BIT,
    PERIPH_STATUS_ADDR,
    RESP_SLVERR,
    SECURE_DMA,
    SepIrqIp,
)

# Two bytes at a word offset + 2 end on the word boundary, so the master issues
# one beat with byte lanes 2 and 3. Four bytes would cross the word and go out as
# a two-beat burst, which a burst-refusing path (hw/sys/sep/doc/crypto.adoc
# "Single-Beat Access Only") answers with DECERR before any beat reaches the block.
# HMAC CFG and Secure DMA INTR_STATE own byte 0, so lanes 2 and 3 miss an owned byte.
_PROBE_BYTES = 2
_PROBE_OFFSET = 2
_RESP_OKAY = 0
# The monitor records an R beat on its own clock edge, which may not have run
# when start_seq returns.
_BEAT_SETTLE_CYCLES = 2


@pyuvm.test()
class sep_periph_bus_err_misaligned_test(sep_base_test):
    """A partial register write must latch the block's bit; a narrow read must not."""

    async def _read_beats(self, name: str, addr: int) -> tuple[SepAxiAccessSeq, list]:
        """Read ``_PROBE_BYTES`` at ``addr`` and return the RRESP of every R beat."""
        mon = self.env.axi_monitor
        mon.start_beat_capture()
        seq = SepAxiAccessSeq(name, op=SepAxiOp.READ, addr=addr, length=_PROBE_BYTES, size=2)
        await self.start_seq(seq)
        await ClockCycles(cocotb.top.clk_i, _BEAT_SETTLE_CYCLES)
        return seq, mon.take_beat_capture()

    async def _status(self) -> tuple[int, int]:
        """Return (PERIPH_BUS_ERR_STATUS, DMA_BUS_ERR_STATUS)."""
        return (
            await self.irq.read32(PERIPH_STATUS_ADDR),
            await self.irq.read32(DMA_STATUS_ADDR),
        )

    async def _probe(
        self, tag: str, block: str, aligned: int, before: tuple[int, int], after: tuple[int, int]
    ) -> None:
        """Grade one block: the aligned read, the narrow read, then the partial write.

        ``before`` is the (PERIPH, DMA) status the two reads must leave unchanged,
        and ``after`` is the exact (PERIPH, DMA) status the partial write must
        leave. Both registers are compared whole, so a bit latched in the other
        register fails too.
        """
        ctrl, beats = await self._read_beats(f"{block}_aligned_rd", aligned)
        status = await self._status()
        assert (ctrl.resp_code, beats, status) == (_RESP_OKAY, [_RESP_OKAY], before), (
            f"{block} aligned read @0x{aligned:08x} returned resp={ctrl.resp_code} over R "
            f"beats {beats} and left (PERIPH, DMA) status=({status[0]:#x}, {status[1]:#x}); "
            f"the control requires one OKAY beat and ({before[0]:#x}, {before[1]:#x})"
        )
        self.logger.info(
            "CHK-MISALIGN%s-CTRL PASS: 0x%08x one OKAY beat rdata=%#x", tag, aligned, ctrl.rdata
        )

        addr = aligned + _PROBE_OFFSET
        narrow, beats = await self._read_beats(f"{block}_narrow_rd", addr)
        status = await self._status()
        assert (narrow.resp_code, beats, status) == (_RESP_OKAY, [_RESP_OKAY], before), (
            f"{block} narrow read @0x{addr:08x} returned resp={narrow.resp_code} over R "
            f"beats {beats} and left (PERIPH, DMA) status=({status[0]:#x}, {status[1]:#x}); "
            f"a narrow read is legal and requires one OKAY beat and "
            f"({before[0]:#x}, {before[1]:#x})"
        )
        self.logger.info("CHK-MISALIGN%s-RD PASS: 0x%08x one OKAY beat, no latch", tag, addr)

        wr = SepAxiAccessSeq(
            f"{block}_partial_wr",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=0xFFFF,
            length=_PROBE_BYTES,
            size=2,
            expect_error=True,
        )
        await self.start_seq(wr)
        status = await self._status()
        readback, _ = await self._read_beats(f"{block}_readback_rd", aligned)
        # The response code needs its own comparison: the scoreboard's expect_error
        # arm accepts any non-OKAY. The readback shows the refused write changed
        # nothing, and the status shows the latch.
        assert (wr.resp_code, status, readback.rdata) == (RESP_SLVERR, after, ctrl.rdata), (
            f"{block} partial write @0x{addr:08x} returned resp={wr.resp_code}, left "
            f"(PERIPH, DMA) status=({status[0]:#x}, {status[1]:#x}) and register "
            f"{readback.rdata:#x}; the contract requires SLVERR ({RESP_SLVERR}), "
            f"({after[0]:#x}, {after[1]:#x}) and the register unchanged at {ctrl.rdata:#x}"
        )
        self.logger.info(
            "CHK-MISALIGN%s-LATCH PASS: 0x%08x SLVERR, latched (PERIPH, DMA)=(%#x, %#x), "
            "register unchanged %#x",
            tag,
            addr,
            *status,
            readback.rdata,
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)

        base = await self._status()
        assert base == (0, 0), (
            f"(PERIPH, DMA) status=({base[0]:#x}, {base[1]:#x}) at baseline, expected (0, 0)"
        )
        self.logger.info("CHK-MISALIGN-BASE PASS: PERIPH/DMA_BUS_ERR_STATUS=0")

        # The HMAC bit stays latched through the DMA probe: nothing clears it,
        # so the DMA expectations carry it unchanged.
        await self._probe("", "hmac", HMAC.addr("CFG"), (0, 0), (PERIPH_HMAC_BIT, 0))
        await self._probe(
            "-DMA",
            "dma",
            SECURE_DMA.addr("INTR_STATE"),
            (PERIPH_HMAC_BIT, 0),
            (PERIPH_HMAC_BIT, DMA_REG_PATH_BIT),
        )
