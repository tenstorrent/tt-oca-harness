# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH_BUS_ERR_STATUS on a misaligned offset.

sep_cpu_ctrl.rdl and doc/interrupts.adoc require SLVERR and the owning
block's bit. The fabric returns DECERR and the bit stays 0.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import (
    PERIPH_HMAC_BIT,
    PERIPH_STATUS_ADDR,
    RESP_DECERR,
    RESP_SLVERR,
    SepIrqIp,
    hmac_misaligned_addr,
)

# Bytes read from the misaligned offset. With the offset inside one 32-bit
# word this stays a single AXI beat (AxLEN=0), so the response and the latched
# bit are attributable to the misaligned offset alone, not to a burst or to a
# second, aligned beat.
_PROBE_BYTES = 2
_BEAT_BYTES = 4


async def _capture_ar(log: list[tuple[int, int, int]]) -> None:
    """Record (araddr, arlen, arsize) for every accepted AR on the s_axi port."""
    top = cocotb.top
    rd = sep_base_test.rd_known
    while True:
        await RisingEdge(top.clk_i)
        await ReadOnly()
        if rd(top.s_axi_arvalid) and rd(top.s_axi_arready):
            log.append((rd(top.s_axi_araddr), rd(top.s_axi_arlen), rd(top.s_axi_arsize)))


@pyuvm.test()
class sep_periph_bus_err_misaligned_test(sep_base_test):
    """A misaligned beat inside a mapped extent must latch the block's bit."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)
        addr = hmac_misaligned_addr()

        base = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert base == 0, f"PERIPH_BUS_ERR_STATUS=0x{base:x} at baseline, expected 0"
        self.logger.info("CHK-MISALIGN-BASE PASS: PERIPH_BUS_ERR_STATUS=0")

        # A standing credit absorbs the next unexpected DECERR anywhere on this
        # bus, so a probe that saw no DECERR beat hands its credits back. Keyed
        # off the response rather than the monitor tally: the monitor counts on
        # its own clock edge, which may not have run when start_seq returns.
        offset = addr % _BEAT_BYTES
        assert offset != 0 and offset + _PROBE_BYTES <= _BEAT_BYTES, (
            f"probe 0x{addr:08x} + {_PROBE_BYTES} bytes is not a misaligned access "
            f"inside one {_BEAT_BYTES}-byte beat"
        )
        mon = self.env.axi_monitor
        # One beat, so one DECERR credit at most.
        mon.arm_expected_decerr(1)
        ar_log: list[tuple[int, int, int]] = []
        watcher = cocotb.start_soon(_capture_ar(ar_log))
        seq = SepAxiAccessSeq(
            "misaligned_rd",
            op=SepAxiOp.READ,
            addr=addr,
            length=_PROBE_BYTES,
            size=2,
            expect_error=True,
        )
        await self.start_seq(seq)
        watcher.kill()
        if seq.timed_out or seq.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)

        assert len(ar_log) == 1, (
            f"misaligned probe issued {len(ar_log)} AR handshakes "
            f"{[(hex(a), n, z) for a, n, z in ar_log]}, expected exactly one"
        )
        ar_addr, ar_len, ar_size = ar_log[0]
        assert (ar_addr, ar_len, ar_size) == (addr, 0, 2), (
            f"misaligned probe AR araddr=0x{ar_addr:08x} arlen={ar_len} arsize={ar_size}, "
            f"expected araddr=0x{addr:08x} arlen=0 arsize=2"
        )
        self.logger.info(
            "CHK-MISALIGN-BEAT PASS: one AR araddr=0x%08x arlen=%d arsize=%d",
            ar_addr,
            ar_len,
            ar_size,
        )

        status = await self.irq.read32(PERIPH_STATUS_ADDR)
        # Both halves of the contract are graded. The status bit alone would go
        # green on an RTL change that latched the bit while still answering
        # DECERR, and the scoreboard's expect_error arm accepts any non-OKAY, so
        # the response code needs its own comparison rather than only appearing
        # in this message.
        assert (seq.resp_code, status) == (RESP_SLVERR, PERIPH_HMAC_BIT), (
            f"misaligned read @0x{addr:08x} returned resp={seq.resp_code} and left "
            f"PERIPH_BUS_ERR_STATUS=0x{status:x}; the contract requires SLVERR "
            f"({RESP_SLVERR}) and the hmac bit 0x{PERIPH_HMAC_BIT:x} latched"
        )
        self.logger.info("CHK-MISALIGN-LATCH PASS: 0x%08x latched STATUS=0x%x", addr, status)
