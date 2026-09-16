# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_trst_test.

TRST_N is asynchronous: the TAP is in Test-Logic-Reset as soon as the pin is
low, before any TCK edge, and stays there through TCK cycles with TMS low,
which would otherwise leave Test-Logic-Reset. After release a single TMS-low
step reaches Run-Test/Idle and a DR scan with no instruction load reads the
device-identification register the reset selected.
"""

from __future__ import annotations

import random

import cocotb
from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr, DtpTapState
from ocah_jtag_vip import OcahJtagChecker

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

IDCODE_MASK = 0xFFFF_FFFF


class dtp_jtag_trst_test_seq(dtp_jtag_base_test_seq):
    """Run asynchronous TRST reset and recovery checks with named evidence."""

    async def reset_from(
        self,
        state: DtpTapState,
        rng: random.Random,
        checker: OcahJtagChecker,
    ) -> tuple[int, bool]:
        """From ``state``, assert TRST_N, judge the reset, release, and read IDCODE."""
        await self.reset_to_tlr()
        await self.load_ir(rng.choice([DtpJtagInstr.BYPASS_3F, DtpJtagInstr.IDCODE]))
        await self.goto_tap_state(state)

        cycles = rng.randint(2, 8)
        item = await self.assert_trst(cycles=cycles)
        context = f"trst_from={state.name} cycles={cycles}"
        checker.check_reset_to_tlr(
            item.reset_state,
            check_id="CHK-TAP-TRST-ASYNC",
            context=f"before any TCK edge {context}",
        )
        checker.check_reset_to_tlr(
            item.result,
            check_id="CHK-TAP-TRST-TLR",
            context=f"after TMS-low TCK cycles under TRST {context}",
        )
        self.record_tap_state(item.result, DtpTapState.TEST_LOGIC_RESET)
        await self.deassert_trst(cycles=rng.randint(1, 3))

        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)
        idcode = await self.shift_dr(0, 32)
        checker.expect_equal(
            "CHK-IDCODE-RAW",
            idcode.result & IDCODE_MASK,
            DTP_DEFAULT_IDCODE,
            context=f"DR scan with no IR load after TRST release {context}",
        )
        return cycles, (idcode.result & IDCODE_MASK) == DTP_DEFAULT_IDCODE

    async def body(self) -> None:
        rng = self.rng("trst")
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.checker",
            logger=cocotb.log,
            required_ids={
                "CHK-TAP-RESET-TLR",
                "CHK-TAP-STATE",
                "CHK-TAP-TRST-ASYNC",
                "CHK-TAP-TRST-TLR",
                "CHK-IDCODE-RAW",
                "CHK-NONVAC",
            },
        )
        self.attach_tap_checker(checker)

        states = [
            DtpTapState.RUN_TEST_IDLE,
            DtpTapState.SHIFT_IR,
            DtpTapState.SHIFT_DR,
            rng.choice([DtpTapState.CAPTURE_IR, DtpTapState.CAPTURE_DR]),
        ]

        trst_cycles: list[int] = []
        idcode_ok = 0
        for idx, state in enumerate(states, start=1):
            self.log_iteration(idx, len(states), "TRST from %s", state.name)
            cycles, recovered = await self.reset_from(state, rng, checker)
            trst_cycles.append(cycles)
            idcode_ok += int(recovered)

        checker.expect_true(
            "CHK-NONVAC",
            len(set(states)) == len(states) and min(trst_cycles) >= 2 and idcode_ok == len(states),
            context=(
                f"start_states={len(set(states))} "
                f"trst_cycles={trst_cycles} idcode_recovered={idcode_ok}/{len(states)}"
            ),
        )
        checker.finalize()
