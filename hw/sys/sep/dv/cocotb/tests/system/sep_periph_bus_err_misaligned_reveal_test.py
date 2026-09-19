# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH_BUS_ERR_STATUS must latch on a misaligned offset.

EXPECTED FAIL. The contract is sep_cpu_ctrl.rdl:383 and doc/interrupts.adoc:241:
a CPU access at a misaligned offset is a TL-UL error, receives SLVERR, and
latches that block's bit. The DUT does not do this. The leaf is left unmarked
so a run of `all` stays a visible fail; a spec-vs-RTL gap is not masked as
`expect_fail`.
"""

from __future__ import annotations

import pyuvm
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


@pyuvm.test()
class sep_periph_bus_err_misaligned_reveal_test(sep_base_test):
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
        mon = self.env.axi_monitor
        mon.arm_expected_decerr(1)
        seq = SepAxiAccessSeq(
            "misaligned_rd", op=SepAxiOp.READ, addr=addr, size=2, expect_error=True
        )
        await self.start_seq(seq)
        if seq.timed_out or seq.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)

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
