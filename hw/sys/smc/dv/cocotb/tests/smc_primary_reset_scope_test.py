# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cores, fabric and peripheral controllers are held while rst_primary_no is asserted.

Closes SMC-RST-PRIMARY.S1, SMC-RST-PRIMARY.S2 and SMC-RST-PRIMARY.S3
(clk_rst.adoc: Primary Reset): with a core fetching ROM, an outbound filter
holding a pattern and UART0 mid-frame, the cool pin asserts the primary reset
and each consumer is sampled every clock edge across the held window -- core
reset low and no ROM fetch, SEP_IN response channels idle, the UART TX pad
driver released -- and the fabric and peripheral registers read their
generated resets after release.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_primary_reset_scope_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_primary_reset_scope_test_seq import (
    EXPECTED_VALUE_CHECKS,
    smc_primary_reset_scope_test_seq,
)
from smc_base_test import smc_base_test

EXPECTED_WAIT_CHECKS = 2


@pyuvm.test()
class smc_primary_reset_scope_test(smc_base_test):
    """Held state of cores, fabric and peripherals under a cool-pin primary reset."""

    async def run_scenario(self) -> None:
        seq = smc_primary_reset_scope_test_seq("primary_reset_scope_seq")

        async def _dispatch(item) -> None:
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = _dispatch
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= EXPECTED_WAIT_CHECKS, (
            f"scoreboard booked {sb.reset_wait_checks_seen} reset WAIT_STATE checks, expected at "
            f"least {EXPECTED_WAIT_CHECKS}"
        )
        assert sb.sys_axi_value_checks_seen >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {sb.sys_axi_value_checks_seen} SEP_IN value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        assert seq.hold_samples > 0 and seq.fetch_delta_before, (
            "the sequence ended without a held window or a fetching-core precondition"
        )
        cocotb.log.info(
            "CHK-PRIMARY-RESET-SCOPE: held window %d samples (core reset low %d, rvalid high %d, "
            "bvalid high %d, UART TX driver enabled after settle %d); scoreboard reset wait checks "
            "%d, SEP_IN value compares %d",
            seq.hold_samples,
            seq.core_reset_low_samples,
            seq.rvalid_high_samples,
            seq.bvalid_high_samples,
            seq.tx_oe_high_after_settle,
            sb.reset_wait_checks_seen,
            sb.sys_axi_value_checks_seen,
        )
