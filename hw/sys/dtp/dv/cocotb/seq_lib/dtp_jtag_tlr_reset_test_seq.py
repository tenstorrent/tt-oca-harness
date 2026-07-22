# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_tlr_reset_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, DtpTapState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_tlr_reset_test_seq(dtp_jtag_base_test_seq):
    """Run TMS-to-Test-Logic-Reset behavior checks."""

    async def body(self) -> None:
        rng = self.rng("tlr_reset")
        states = [
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SHIFT_IR,
            DtpTapState.SHIFT_DR,
            rng.choice([DtpTapState.PAUSE_IR, DtpTapState.PAUSE_DR]),
        ]

        for state in states:
            await self.reset_to_tlr()
            await self.load_ir(DtpJtagInstr.BYPASS_3F)
            await self.goto_tap_state(state)

            for _ in range(rng.randint(5, 8)):
                await self.tms_expect(1)
            self.record_tap_state(int(DtpTapState.TEST_LOGIC_RESET), DtpTapState.TEST_LOGIC_RESET)

            idcode = await self.shift_dr(0, 32)
            assert idcode.result == DTP_DEFAULT_IDCODE, (
                f"TLR from {state.name} did not restore default IDCODE DR: "
                f"expected 0x{DTP_DEFAULT_IDCODE:08x}, got 0x{idcode.result:08x}"
            )
