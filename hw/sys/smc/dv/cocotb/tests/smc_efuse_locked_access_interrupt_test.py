# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse locked-shadow access IRQ. Not map/LC."""

from __future__ import annotations

import cocotb
import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_locked_access_interrupt_test_seq import (
    smc_efuse_locked_access_interrupt_test_seq,
)


@pyuvm.test()
class smc_efuse_locked_access_interrupt_test(smc_base_test):
    """CHIPLET_ID unlocked write silent; locked write/read pulse bit 28."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        sb = self.env.scoreboard
        before = sb.sys_axi_value_checks_seen
        seq = smc_efuse_locked_access_interrupt_test_seq("efuse_lock_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

        # The fail-capable proof lives in the sequence: the interrupt edge counts
        # are exact, the locked read is compared by the scoreboard against an
        # expectation stated before the access, and the non-disclosure assert is
        # independent of the sentinel. None of that is restated here.
        #
        # What this gate adds is a quantity the sequence does not produce: the
        # number of exact rdata compares the SCOREBOARD booked on its own
        # analysis path. The scoreboard increments it only after `got == exp`
        # passed, so a leg that silently lost its `expected=`, or an analysis
        # port that came unbound, drops the delta below the floor and fails here
        # while every sequence-side assert still passes.
        _EXPECTED_VALUE_CHECKS = 2  # LOCKS_PRE (asset word) + CHIPLET_ID_LOCK_RD
        measured = sb.sys_axi_value_checks_seen - before
        assert measured >= _EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {measured} SEP_IN AXI exact-value compares "
            f"for this scenario, expected at least {_EXPECTED_VALUE_CHECKS} "
            f"(LOCKS reset word, read-locked CHIPLET_ID read)"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-SCOREBOARD: %d >= %d exact-value compares booked by "
            "the scoreboard; measured IRQ edges unlock=%d wr=%d rd=%d",
            measured,
            _EXPECTED_VALUE_CHECKS,
            seq.unlock_edges,
            seq.wr_edges,
            seq.rd_edges,
        )
