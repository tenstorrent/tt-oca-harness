# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH_BUS_ERR_STATUS on a misaligned offset.

sep_cpu_ctrl.rdl and doc/interrupts.adoc require a misaligned offset to receive
SLVERR and latch the owning block's PERIPH_BUS_ERR_STATUS bit.
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
    PERIPH_HMAC_BIT,
    PERIPH_STATUS_ADDR,
    RESP_SLVERR,
    SepIrqIp,
    hmac_misaligned_addr,
)

# Two bytes at CFG+2 end on the word boundary, so the master issues one beat.
# Four bytes would cross the word and go out as a two-beat burst, and
# doc/crypto.adoc "Single-Beat Access Only" refuses every burst with DECERR
# before any beat reaches an accelerator.
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

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)
        addr = hmac_misaligned_addr()

        base = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert base == 0, f"PERIPH_BUS_ERR_STATUS=0x{base:x} at baseline, expected 0"
        self.logger.info("CHK-MISALIGN-BASE PASS: PERIPH_BUS_ERR_STATUS=0")

        # The same single-beat shape at the aligned CFG offset. It must be
        # accepted and must not latch, so the probe below differs from an
        # accepted access only in address bits [1:0].
        aligned = HMAC.addr("CFG")
        ctrl, beats = await self._read_beats("aligned_rd", aligned)
        status = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert (ctrl.resp_code, beats, status) == (_RESP_OKAY, [_RESP_OKAY], 0), (
            f"aligned read @0x{aligned:08x} returned resp={ctrl.resp_code} over R beats "
            f"{beats} and left PERIPH_BUS_ERR_STATUS=0x{status:x}; the control requires "
            f"one OKAY beat and the register still 0"
        )
        self.logger.info("CHK-MISALIGN-CTRL PASS: 0x%08x one OKAY beat, STATUS=0", aligned)

        seq, beats = await self._read_beats("misaligned_rd", addr)
        # One beat is what makes this a misaligned-offset probe: a burst is
        # refused before it reaches the block's alignment check.
        assert beats == [RESP_SLVERR], (
            f"misaligned read @0x{addr:08x} returned R beats {beats}; the probe requires "
            f"one beat answered SLVERR ({RESP_SLVERR})"
        )
        self.logger.info("CHK-MISALIGN-BEAT PASS: 0x%08x one SLVERR beat", addr)

        status = await self.irq.read32(PERIPH_STATUS_ADDR)
        # Both halves of the contract are graded. The status bit alone would go
        # green on an RTL change that latched the bit while answering another
        # code, and the scoreboard's expect_error arm accepts any non-OKAY, so
        # the response code needs its own comparison rather than only appearing
        # in this message.
        assert (seq.resp_code, status) == (RESP_SLVERR, PERIPH_HMAC_BIT), (
            f"misaligned read @0x{addr:08x} returned resp={seq.resp_code} and left "
            f"PERIPH_BUS_ERR_STATUS=0x{status:x}; the contract requires SLVERR "
            f"({RESP_SLVERR}) and the hmac bit 0x{PERIPH_HMAC_BIT:x} latched"
        )
        self.logger.info("CHK-MISALIGN-LATCH PASS: 0x%08x latched STATUS=0x%x", addr, status)
