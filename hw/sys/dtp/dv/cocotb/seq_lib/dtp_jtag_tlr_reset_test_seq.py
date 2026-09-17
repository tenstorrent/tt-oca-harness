# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tlr_reset_test.

Five or more TMS-high TCK cycles force Test-Logic-Reset from any state. TLR
re-selects the device-identification register over the loaded instruction,
returns DEBUG_CONTROL to 0x00 and IC_RESET (written with reset_hold = 1) to its
all-ones default with the pin outputs of both following, and leaves the TAP
ready for instruction-register access from Run-Test/Idle.
"""

from __future__ import annotations

import random

import cocotb
from env.dtp_tap_device import DTP_DEFAULT_IDCODE, DTP_IC_RESET_LEN
from env.dtp_types import DtpJtagInstr, DtpTapState
from ocah_jtag_vip import OcahJtagChecker
from ocah_lib import OcahKnobs

from .dtp_debug_tdr_base_test_seq import DEBUG_OUTPUT_DEFAULTS, dtp_debug_tdr_base_test_seq

IDCODE_MASK = 0xFFFF_FFFF
TDR_DEFAULT_CHECK_ID = "CHK-TLR-TDR-DEFAULT"
RESUME_CHECK_ID = "CHK-TLR-RESUME"
IC_RESET_PORTS = ("smc", "sep", "ext")
# Non-default DEBUG_CONTROL image: boot stall, its override, and the CLA
# clock-stop enable set; the clock-stop request bits stay clear.
PROGRAMMED_DEBUG_CONTROL = dtp_debug_tdr_base_test_seq.pack_debug_control(
    boot_stall=1, boot_stall_ovrd=1, cla_clock_stop_en=1
)
# Pin image of the programmed TDRs: an active (0) slice enable drives
# {ovrd=1, ctrl_n=0}.
PROGRAMMED_DEBUG_OUTPUTS: dict[str, int] = {
    "stop_clks": 0,
    "cla_clock_stop_en": 1,
    "jtag_boot_stall": 1,
    "jtag_boot_stall_ovrd": 1,
    **{f"jtag_ic_reset_{port}_ovrd": 1 for port in IC_RESET_PORTS},
    **{f"jtag_ic_reset_{port}_ctrl_n": 0 for port in IC_RESET_PORTS},
}


class dtp_jtag_tlr_reset_test_seq(dtp_debug_tdr_base_test_seq):
    """Run TMS-to-Test-Logic-Reset checks against the TAP reference model."""

    async def program_debug_tdrs(self) -> None:
        """Write non-default DEBUG_CONTROL and IC_RESET images; the pins follow them."""
        await self.write_debug_control(PROGRAMMED_DEBUG_CONTROL)
        await self.write_ic_reset(
            reset_hold=1,
            reset_enable={port: 0 for port in IC_RESET_PORTS},
            reset_control={port: 0 for port in IC_RESET_PORTS},
        )
        await self.wait_sys_cycles()
        self.check_debug_outputs(
            TDR_DEFAULT_CHECK_ID,
            await self.snapshot_debug_outputs(),
            PROGRAMMED_DEBUG_OUTPUTS,
            context="programmed before TLR",
        )

    async def check_tdr_defaults(self, context: str) -> None:
        """Pin outputs and TDR readbacks at their defaults after Test-Logic-Reset."""
        await self.wait_sys_cycles()
        self.check_debug_outputs(
            TDR_DEFAULT_CHECK_ID,
            await self.snapshot_debug_outputs(),
            DEBUG_OUTPUT_DEFAULTS,
            context=context,
        )
        self.family_check(
            TDR_DEFAULT_CHECK_ID,
            "DEBUG_CONTROL readback",
            await self.read_debug_control(),
            0,
            context=context,
        )
        default_ic_reset = self.bit_mask(DTP_IC_RESET_LEN)
        self.family_check(
            TDR_DEFAULT_CHECK_ID,
            "IC_RESET readback",
            await self.read_ic_reset(shift_value=default_ic_reset),
            default_ic_reset,
            context=context,
        )

    async def walk_to_tlr(
        self,
        state: DtpTapState,
        rng: random.Random,
        checker: OcahJtagChecker,
        *,
        negative: bool,
    ) -> tuple[int, bool]:
        """From ``state`` with BYPASS loaded, walk TMS high into TLR and judge the reset."""
        await self.reset_to_tlr()
        await self.program_debug_tdrs()
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
        item = await self.sample_observables()
        checker.check_tms_ones_to_tlr(ones, item.result, context=f"from={state.name}")

        context = f"from={state.name} tms_ones={ones}"
        idcode = await self.shift_dr(0, 32)
        checker.expect_equal(
            "CHK-TAP-TLR-IDCODE",
            idcode.result & IDCODE_MASK,
            DTP_DEFAULT_IDCODE,
            context=context,
        )
        await self.check_tdr_defaults(context=f"after TLR {context}")
        await self.load_ir(DtpJtagInstr.IDCODE)
        resumed = await self.shift_dr(0, 32)
        checker.expect_equal(
            RESUME_CHECK_ID,
            resumed.result & IDCODE_MASK,
            DTP_DEFAULT_IDCODE,
            context=f"IDCODE by IR scan after TLR {context}",
        )
        return ones, (idcode.result & IDCODE_MASK) == DTP_DEFAULT_IDCODE

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
                TDR_DEFAULT_CHECK_ID,
                RESUME_CHECK_ID,
                "CHK-NONVAC",
            },
        )
        self.attach_tap_checker(checker)
        # DTP_JTAG_TAP_CHECKER_NEGATIVE=1 is the documented negative-validation
        # hook: it desyncs the TAP reference model so the next
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
        for idx, state in enumerate(states, start=1):
            self.log_iteration(idx, len(states), "TMS-high walk to TLR from %s", state.name)
            ones, restored = await self.walk_to_tlr(state, rng, checker, negative=negative)
            ones_counts.append(ones)
            idcode_ok += int(restored)

        checker.expect_true(
            "CHK-NONVAC",
            len(set(states)) == len(states) and min(ones_counts) >= 5 and idcode_ok == len(states),
            context=(
                f"start_states={len(set(states))} "
                f"tms_ones={ones_counts} idcode_restored={idcode_ok}/{len(states)}"
            ),
        )
        checker.finalize()
