# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tlr_reset_test."""

from __future__ import annotations

import cocotb
from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, DtpTapState
from ocah_jtag_vip import OcahJtagChecker
from ocah_lib import OcahKnobs

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_tlr_reset_test_seq(dtp_jtag_base_test_seq):
    """Run TMS-to-Test-Logic-Reset behavior checks against the TAP reference model."""

    async def body(self) -> None:
        rng = self.rng("tlr_reset")
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.checker",
            logger=cocotb.log,
            required_ids={
                "CHK-TAP-RESET-TLR",
                "CHK-TAP-STATE",
                "CHK-TAP-TLR-TMS5",
                "CHK-TAP-TLR-IDCODE",
                "CHK-NONVAC",
            },
        )
        self.attach_tap_checker(checker)
        # DTP_JTAG_TAP_CHECKER_NEGATIVE=1 is the documented negative-validation
        # hook: it deliberately desyncs the TAP reference model so the next
        # state check must FAIL, proving the checker rejects a bad prediction
        # end to end.
        negative = OcahKnobs.is_set("DTP_JTAG_TAP_CHECKER_NEGATIVE")

        states = [
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SHIFT_IR,
            DtpTapState.SHIFT_DR,
            rng.choice([DtpTapState.PAUSE_IR, DtpTapState.PAUSE_DR]),
        ]

        ones_counts: list[int] = []
        idcode_ok = 0
        for state in states:
            await self.reset_to_tlr()
            await self.load_ir(DtpJtagInstr.BYPASS_3F)
            await self.goto_tap_state(state)

            if negative:
                # TEST_LOGIC_RESET is never the true pre-walk state here and
                # its TMS=1 successor (itself) differs from every legal
                # successor of the states above, so the first walk step must
                # produce a CHK-TAP-STATE FAIL.
                self.log.warning(
                    "NEGATIVE VALIDATION: desyncing TAP reference model to "
                    "TEST_LOGIC_RESET before the TMS-high walk from %s",
                    state.name,
                )
                checker.sync_state(DtpTapState.TEST_LOGIC_RESET)

            ones = rng.randint(5, 8)
            for _ in range(ones):
                await self.tms_expect(1)
            ones_counts.append(ones)

            item = await self.sample_observables()
            checker.check_tms_ones_to_tlr(
                ones,
                item.result,
                context=f"from={state.name}",
            )

            idcode = await self.shift_dr(0, 32)
            checker.expect_equal(
                "CHK-TAP-TLR-IDCODE",
                idcode.result & 0xFFFF_FFFF,
                DTP_DEFAULT_IDCODE,
                context=f"from={state.name} tms_ones={ones}",
            )
            if (idcode.result & 0xFFFF_FFFF) == DTP_DEFAULT_IDCODE:
                idcode_ok += 1

        checker.expect_true(
            "CHK-NONVAC",
            len(set(states)) == len(states) and min(ones_counts) >= 5 and idcode_ok == len(states),
            context=(
                f"start_states={len(set(states))} "
                f"tms_ones={ones_counts} idcode_restored={idcode_ok}/{len(states)}"
            ),
        )
        checker.finalize()
