# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cores and peripherals held, and the fabric registers reverted, under a cool reset.

Closes SMC-RST-PRIMARY.S1 and SMC-RST-PRIMARY.S3 (clk_rst.adoc: Primary
Reset): with a core fetching ROM and UART0 mid-frame, the cool pin asserts the
primary reset and each of those consumers is sampled every clock edge across
the held window -- core reset low and no ROM fetch, the UART TX pad driver
released -- and the peripheral registers read their generated resets after
release.

SMC-RST-PRIMARY.S2, the fabric half, is narrowed to what this bench can
observe: an outbound filter register holds a pattern before the reset and
reads its generated reset after it, so the primary reset reached the fabric
configuration registers. Held-state at the SEP_IN boundary is not claimed --
ready is not withdrawn under primary reset and the SEP_IN master shares that
reset, so no request can be presented inside the window. The sequence
docstring gives both measurements.

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
    """Cores and peripherals held, and the fabric registers reverted, under a cool reset."""

    required_evidence = (
        "CHK-PRIMARY-RESET-CORES-HELD",
        "CHK-PRIMARY-RESET-FABRIC-REVERTED",
        "CHK-PRIMARY-RESET-PERIPHERALS-HELD",
        "CHK-PRIMARY-RESET-SCOPE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

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
        assert seq.hold_samples > 0 and seq.fetch_delta_after, (
            "the sequence ended without a held window or a fetching-core precondition"
        )
        cocotb.log.info(
            "CHK-PRIMARY-RESET-SCOPE: held window %d samples (core reset low %d, UART TX driver "
            "enabled after settle %d; recorded SEP_IN tallies arready %d, awready %d, arvalid %d, "
            "rvalid %d, bvalid %d); scoreboard reset wait checks %d, SEP_IN value compares %d",
            seq.hold_samples,
            seq.core_reset_low_samples,
            seq.tx_oe_high_after_settle,
            seq.arready_high_samples,
            seq.awready_high_samples,
            seq.arvalid_high_samples,
            seq.rvalid_high_samples,
            seq.bvalid_high_samples,
            sb.reset_wait_checks_seen,
            sb.sys_axi_value_checks_seen,
        )
