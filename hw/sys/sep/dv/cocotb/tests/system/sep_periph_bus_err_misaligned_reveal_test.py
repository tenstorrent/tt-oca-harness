# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PERIPH_BUS_ERR_STATUS must latch on a misaligned offset.

EXPECTED FAIL. The contract is sep_cpu_ctrl.rdl:383 and doc/interrupts.adoc:227:
a CPU access at a misaligned offset is a TL-UL error, receives SLVERR, and
latches that block's bit. The DUT does not do this. The framework has no xfail
mechanism, so a run whose only failure is this leaf is the expected result.

Tracked by https://github.com/tenstorrent/tt-oca-harness/issues/1993.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import (
    PERIPH_HMAC_BIT,
    RESP_SLVERR,
    PERIPH_STATUS_ADDR,
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

        mon = self.env.axi_monitor
        mon.arm_expected_decerr(2)
        seen = mon.expected_decerr_seen
        seq = SepAxiAccessSeq(
            "misaligned_rd", op=SepAxiOp.READ, addr=addr, size=2, expect_error=True
        )
        await self.start_seq(seq)
        unused = 2 - (mon.expected_decerr_seen - seen)
        if unused > 0:
            mon.release_expected_decerr(unused)

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
        self.logger.info(
            "CHK-MISALIGN-LATCH PASS: 0x%08x latched STATUS=0x%x", addr, status
        )
