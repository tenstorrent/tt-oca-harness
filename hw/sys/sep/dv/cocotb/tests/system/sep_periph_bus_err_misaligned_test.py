# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH_BUS_ERR_STATUS and DMA_BUS_ERR_STATUS on a misaligned offset.

sep_cpu_ctrl.rdl and doc/interrupts.adoc require a misaligned offset to receive
SLVERR and latch the owning block's bit: the HMAC bit of PERIPH_BUS_ERR_STATUS
for an HMAC register, and reg_path_err of DMA_BUS_ERR_STATUS for a Secure DMA
register.
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
# one beat. Four bytes would cross the word and go out as a two-beat burst,
# which a burst-refusing path (doc/crypto.adoc "Single-Beat Access Only")
# answers with DECERR before any beat reaches the block.
_PROBE_BYTES = 2
_RESP_OKAY = 0
# The monitor records an R beat on its own clock edge, which may not have run
# when start_seq returns.
_BEAT_SETTLE_CYCLES = 2


@pyuvm.test()
class sep_periph_bus_err_misaligned_test(sep_base_test):
    """A misaligned beat inside a mapped extent must latch the block's bit."""

    async def _read_beats(self, name: str, addr: int) -> tuple[SepAxiAccessSeq, list]:
        """Read ``_PROBE_BYTES`` at ``addr`` and return the RRESP of every R beat."""
        mon = self.env.axi_monitor
        mon.start_beat_capture()
        seq = SepAxiAccessSeq(
            name,
            op=SepAxiOp.READ,
            addr=addr,
            length=_PROBE_BYTES,
            size=2,
            expect_error=addr % 4 != 0,
        )
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
        """Grade one block: the aligned control, then the single misaligned beat.

        ``before`` is the (PERIPH, DMA) status the control must leave unchanged,
        and ``after`` is the exact (PERIPH, DMA) status the misaligned beat must
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
        self.logger.info("CHK-MISALIGN%s-CTRL PASS: 0x%08x one OKAY beat", tag, aligned)

        addr = aligned + 2
        seq, beats = await self._read_beats(f"{block}_misaligned_rd", addr)
        # One beat is what makes this a misaligned-offset probe: a burst can be
        # refused before it reaches the block's alignment check.
        assert beats == [RESP_SLVERR], (
            f"{block} misaligned read @0x{addr:08x} returned R beats {beats}; the probe "
            f"requires one beat answered SLVERR ({RESP_SLVERR})"
        )
        self.logger.info("CHK-MISALIGN%s-BEAT PASS: 0x%08x one SLVERR beat", tag, addr)

        status = await self._status()
        # Both halves of the contract are graded. The status bit alone would go
        # green on an RTL change that latched the bit while answering another
        # code, and the scoreboard's expect_error arm accepts any non-OKAY, so
        # the response code needs its own comparison rather than only appearing
        # in this message.
        assert (seq.resp_code, status) == (RESP_SLVERR, after), (
            f"{block} misaligned read @0x{addr:08x} returned resp={seq.resp_code} and left "
            f"(PERIPH, DMA) status=({status[0]:#x}, {status[1]:#x}); the contract requires "
            f"SLVERR ({RESP_SLVERR}) and ({after[0]:#x}, {after[1]:#x})"
        )
        self.logger.info(
            "CHK-MISALIGN%s-LATCH PASS: 0x%08x latched (PERIPH, DMA)=(%#x, %#x)",
            tag,
            addr,
            *status,
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
