# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_bypass_test.

Checks both DTP BYPASS instruction encodings using raw IR/DR scans.
"""

from __future__ import annotations

import cocotb
from env.dtp_jtag_bypass_model import DtpBypassRefModel, DtpBypassSuiteCfg
from ocah_jtag_vip import OcahJtagChecker

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run BYPASS latency checks for IR=0x00 and IR=0x3f."""

    async def body(self) -> None:
        seed = (
            self.scenario_seed if self.scenario_seed is not None else self.random_seed()
        )
        suite = DtpBypassSuiteCfg.from_seed(seed, random_count=self.random_count)
        model = DtpBypassRefModel()
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.checker",
            raise_on_error=False,
            required_ids={"CHK-BYPASS-00", "CHK-BYPASS-3F", "CHK-NONVAC"},
            logger=cocotb.log,
        )

        self.log.info(
            "DTP BYPASS suite config: seed=%d cases=%d opcodes=%s",
            suite.seed,
            len(suite.cases),
            sorted({f"0x{case.instruction:02x}" for case in suite.cases}),
        )
        await self.reset_tap()

        delayed_observations = 0
        observed_opcodes: set[int] = set()
        observed_patterns: set[int] = set()
        for index, case in enumerate(suite.cases, start=1):
            self.log_iteration(index, len(suite.cases), case.context)
            await self.load_ir(case.instruction)
            item = await self.shift_dr(case.pattern, case.width)

            mask = (1 << case.width) - 1
            observed = item.result & mask
            expected = model.predict(case)
            checker.expect_equal(
                case.check_id,
                observed,
                expected,
                context=f"seed={suite.seed} {case.context}",
            )

            observed_opcodes.add(case.instruction)
            observed_patterns.add(case.pattern)
            if observed == expected and observed != model.direct_passthrough(case):
                delayed_observations += 1

        checker.expect_true(
            "CHK-NONVAC",
            len(observed_opcodes) == 2
            and len(observed_patterns) >= 6
            and delayed_observations > 0,
            context=(
                f"seed={suite.seed} cases={len(suite.cases)} "
                f"opcodes={len(observed_opcodes)} patterns={len(observed_patterns)} "
                f"delayed_observations={delayed_observations}"
            ),
        )
        checker.finalize()
