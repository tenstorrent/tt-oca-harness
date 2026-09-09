# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_bypass_test.

Checks both DTP BYPASS instruction encodings using raw IR/DR scans, with a
passive OCAH JTAG monitor providing scan-length evidence and the shared TAP
reference model providing one-TCK BYPASS latency evidence.
"""

from __future__ import annotations

import cocotb
from env.dtp_jtag_bypass_model import DtpBypassRefModel, DtpBypassSuiteCfg
from env.dtp_tb_if import JTAG_SIGNAL_MAP
from env.dtp_types import DTP_IR_WIDTH
from ocah_jtag_vip import OcahJtagChecker, OcahJtagMasterMonitor

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run BYPASS latency checks for IR=0x00 and IR=0x3f."""

    async def body(self) -> None:
        seed = self.scenario_seed
        suite = DtpBypassSuiteCfg.from_seed(seed, random_count=self.random_count)
        model = DtpBypassRefModel()
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.checker",
            raise_on_error=False,
            required_ids={
                "CHK-BYPASS-00",
                "CHK-BYPASS-3F",
                "CHK-BYPASS-LATENCY",
                "CHK-TAP-RESET-TLR",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
            logger=cocotb.log,
        )
        self.attach_tap_checker(checker)
        monitor = OcahJtagMasterMonitor(
            self.cfg.tb_if.jtag,
            name=f"{self.get_name()}.monitor",
            signal_map=JTAG_SIGNAL_MAP,
        )
        await monitor.start()

        self.log.info(
            "DTP BYPASS suite config: seed=%d cases=%d opcodes=%s",
            suite.seed,
            len(suite.cases),
            sorted({f"0x{case.instruction:02x}" for case in suite.cases}),
        )
        await self.reset_to_tlr()

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
            checker.check_bypass_latency(
                item.result,
                pattern=case.pattern,
                width=case.width,
                capture_bit=case.capture_bit,
                instruction=case.instruction,
                context=f"seed={suite.seed} {case.context}",
            )

            observed_opcodes.add(case.instruction)
            observed_patterns.add(case.pattern)
            if observed == expected and observed != model.direct_passthrough(case):
                delayed_observations += 1

        await monitor.stop()
        ir_items = monitor.get_ir_transactions()
        dr_items = monitor.get_dr_transactions()
        checker.expect_equal(
            "CHK-SCAN-COUNT",
            (len(ir_items), len(dr_items)),
            (len(suite.cases), len(suite.cases)),
            context=f"monitored (ir, dr) scans for {len(suite.cases)} cases",
        )
        if len(ir_items) == len(suite.cases) and len(dr_items) == len(suite.cases):
            for case, ir_item, dr_item in zip(suite.cases, ir_items, dr_items):
                checker.check_scan_length(
                    ir_item,
                    expected_width=DTP_IR_WIDTH,
                    context=case.context,
                )
                checker.check_scan_length(
                    dr_item,
                    expected_width=case.width,
                    context=case.context,
                )

        checker.expect_true(
            "CHK-NONVAC",
            len(observed_opcodes) == 2 and len(observed_patterns) >= 6 and delayed_observations > 0,
            context=(
                f"seed={suite.seed} cases={len(suite.cases)} "
                f"opcodes={len(observed_opcodes)} patterns={len(observed_patterns)} "
                f"delayed_observations={delayed_observations}"
            ),
        )
        checker.finalize()
