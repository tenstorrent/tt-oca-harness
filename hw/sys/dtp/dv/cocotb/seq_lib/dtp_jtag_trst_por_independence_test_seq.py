# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_trst_por_independence_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, DtpTapState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_trst_por_independence_test_seq(dtp_jtag_base_test_seq):
    """Run POR-only TAP reset checks while TRST_N stays deasserted."""

    async def body(self) -> None:
        rng = self.rng("trst_por_independence")
        state = rng.choice(
            [
                DtpTapState.RUN_TEST_IDLE,
                DtpTapState.SHIFT_IR,
                DtpTapState.SHIFT_DR,
                DtpTapState.PAUSE_IR,
                DtpTapState.PAUSE_DR,
            ]
        )

        await self.reset_to_tlr()
        await self.deassert_trst(cycles=1)
        await self.load_ir(rng.choice([DtpJtagInstr.BYPASS_3F, DtpJtagInstr.IDCODE]))
        await self.goto_tap_state(state)

        item = await self.pulse_por(cycles=rng.randint(2, 8))
        self.record_tap_state(item.result, DtpTapState.TEST_LOGIC_RESET)

        await self.reset_tap()
        idcode = await self.read_idcode()
        assert idcode.result == DTP_DEFAULT_IDCODE, (
            f"IDCODE recovery after POR failed: expected 0x{DTP_DEFAULT_IDCODE:08x}, "
            f"got 0x{idcode.result:08x}"
        )
