# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO ACCESS_FILTER AxPROT."""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_gpio_filter_access_sep_test_seq import (
    smc_gpio_filter_access_sep_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_filter_access_sep_test(smc_base_test):
    """GPIO0/1 ACCESS_FILTER: only the AxPROT equal to the requirement passes (read + write)."""

    required_evidence = (
        "CHK-GPIO-FILTER-GPIO1",
        "CHK-GPIO-FILTER-PRE",
        "CHK-GPIO-FILTER-PRIV",
        "CHK-GPIO-FILTER-SCOREBOARD",
        "CHK-GPIO-FILTER-SWEEP",
        "CHK-GPIO-FILTER-UNPRIV",
        "CHK-GPIO-FILTER-WR-DENY",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        sb = self.env.scoreboard
        before = sb.sys_axi_value_checks_seen
        seq = smc_gpio_filter_access_sep_test_seq("gpio_filter_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

        # The number of exact rdata compares the scoreboard booked on its own
        # analysis path, incremented only after `got == exp` passed: a leg that
        # lost its `expected=`, or an analysis port that came unbound, drops the
        # delta below the floor.
        # GPIO0 pre / priv / priv-write readback, GPIO1 priv, and per requirement
        # value of the sweep one admitted read and one readback, plus the relock.
        _EXPECTED_VALUE_CHECKS = 4 + 8 * 2 + 1
        measured = sb.sys_axi_value_checks_seen - before
        assert measured >= _EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {measured} SEP_IN AXI exact-value compares "
            f"for this scenario, expected at least {_EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-GPIO-FILTER-SCOREBOARD: %d >= %d exact-value compares booked; "
            "denied-access response codes observed: %s",
            measured,
            _EXPECTED_VALUE_CHECKS,
            seq.denied_resps,
        )
