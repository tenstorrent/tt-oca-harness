# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_trst_por_independence_test.

Power-on reset alone, with TRST_N held high and TCK idle, forces the TAP into
Test-Logic-Reset and reloads the device-identification register over the
instruction loaded before it, and the tb_top assertion counter records the
pulse. After the pulse a single TMS-low step reaches Run-Test/Idle and a DR
scan with no instruction load and no TRST activity reads IDCODE.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import RESET_COUNT_CHECK_ID, DtpTapState

from .dtp_jtag_base_test_seq import NON_IDCODE_PRELOADS, dtp_jtag_base_test_seq

IDCODE_MASK = 0xFFFF_FFFF
POR_CHECK_ID = "CHK-TAP-POR-TLR"


class dtp_jtag_trst_por_independence_test_seq(dtp_jtag_base_test_seq):
    """Run POR-only TAP reset checks while TRST_N stays deasserted."""

    async def body(self) -> None:
        checker = await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-TAP-STATE",
                POR_CHECK_ID,
                "CHK-IDCODE-RECOVERY",
                RESET_COUNT_CHECK_ID,
            },
            # Navigating into the Pause states crosses Shift -> Exit1 and
            # publishes partial scans the sequence cannot count, so the
            # pin-level scan monitor stays off.
            use_monitor=False,
        )
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
        cycles = rng.randint(2, 8)
        context = f"start_state={state.name} por_cycles={cycles}"

        self.log_step(1, "Park the TAP in %s with TRST_N released", state.name)
        await self.reset_to_tlr()
        await self.deassert_trst(cycles=1)
        await self.load_ir(rng.choice(NON_IDCODE_PRELOADS))
        await self.goto_tap_state(state)

        self.log_step(2, "Hold power-on reset for %d TCK periods with TCK idle", cycles)
        item = await self.pulse_por(cycles=cycles)
        self.family_check(
            POR_CHECK_ID,
            "TAP state during POR",
            item.result,
            int(DtpTapState.TEST_LOGIC_RESET),
            context=context,
        )
        self.family_check(
            POR_CHECK_ID,
            "TRST_N deasserted during POR",
            item.signals["jtag_trst"],
            1,
            context=context,
        )
        self.record_tap_state(item.result, DtpTapState.TEST_LOGIC_RESET)
        checker.sync_state(DtpTapState.TEST_LOGIC_RESET)

        self.log_step(3, "TLR -> RTI by TMS, then a DR scan with no IR load reads IDCODE")
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)
        idcode = await self.shift_dr(0, 32)
        self.family_check(
            "CHK-IDCODE-RECOVERY",
            "IDCODE DR scan after POR, no IR load, no TRST",
            idcode.result & IDCODE_MASK,
            DTP_DEFAULT_IDCODE,
            context=context,
        )
        await self.finalize_family_checker()
