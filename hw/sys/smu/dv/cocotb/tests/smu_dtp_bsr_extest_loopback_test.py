# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_bsr_extest_loopback_test - P4 EXTEST BSR scan loopback.

Loads IR=EXTEST, shifts compact 8-bit patterns through the TB scan_in<-scan_out
loopback, and checks TDO matches. Also checks one-hot EXTEST decode.

Does NOT claim functional pad BSR or SEP STAP.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    DTP_BSR_MODEL_LEN,
    DTP_EXTEST_DECODED_BIT,
    DTP_IR_EXTEST,
    make_smu_jtag_tap,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

_PATTERNS = (0x00, 0xFF, 0xA5, 0x5A, 0xC3, 0x3C)


@pyuvm.test()
class smu_dtp_bsr_extest_loopback_test(smu_base_test):
    """EXTEST DR loopback + instruction decode."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        await jtag.shift_ir(DTP_IR_EXTEST)
        await ClockCycles(dut.clk_smu_i, 4)

        decoded = int(dut.jtag_ptap_inst_decoded.value)
        expect_onehot = 1 << DTP_EXTEST_DECODED_BIT
        sb.expect_eq(
            "EXTEST decode one-hot",
            decoded,
            expect_onehot,
            evidence="BSR_EXTEST_DECODE",
        )

        mask = (1 << DTP_BSR_MODEL_LEN) - 1
        for pattern in _PATTERNS:
            captured = await jtag.shift_dr(
                pattern & mask,
                width=DTP_BSR_MODEL_LEN,
                back_to_rti=True,
            )
            sb.expect_eq(
                f"BSR_EXTEST_TDO_MATCH pat=0x{pattern:02x}",
                int(captured) & mask,
                pattern & mask,
                evidence="BSR_EXTEST_TDO_MATCH",
            )

        self.logger.info(
            "smu_dtp_bsr_extest_loopback_test: BSR_EXTEST_TDO_MATCH %d patterns",
            len(_PATTERNS),
        )
