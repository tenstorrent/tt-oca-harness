# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_trst_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, DtpTapState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_trst_test_seq(dtp_jtag_base_test_seq):
    """Run asynchronous TRST reset and recovery checks."""

    async def body(self) -> None:
        rng = self.rng("trst")
        states = [
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SHIFT_IR,
            DtpTapState.SHIFT_DR,
            rng.choice([DtpTapState.CAPTURE_IR, DtpTapState.CAPTURE_DR]),
        ]

        for state in states:
            await self.reset_to_tlr()
            await self.load_ir(rng.choice([DtpJtagInstr.BYPASS_3F, DtpJtagInstr.IDCODE]))
            await self.goto_tap_state(state)

            item = await self.assert_trst(cycles=rng.randint(2, 8))
            self.record_tap_state(item.result, DtpTapState.TEST_LOGIC_RESET)
            await self.deassert_trst(cycles=rng.randint(1, 3))

            await self.reset_tap()
            idcode = await self.read_idcode()
            assert idcode.result == DTP_DEFAULT_IDCODE, (
                f"IDCODE recovery after TRST from {state.name} failed: "
                f"expected 0x{DTP_DEFAULT_IDCODE:08x}, got 0x{idcode.result:08x}"
            )
