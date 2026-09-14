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
    """GPIO0/1 ACCESS_FILTER: AxPROT=1 allowed, AxPROT=0 refused (read + write)."""

    required_evidence = (
        "CHK-GPIO-FILTER-GPIO1",
        "CHK-GPIO-FILTER-PRE",
        "CHK-GPIO-FILTER-PRIV",
        "CHK-GPIO-FILTER-SCOREBOARD",
        "CHK-GPIO-FILTER-UNPRIV",
        "CHK-GPIO-FILTER-WR-DENY",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        sb = self.env.scoreboard
        before = sb.sys_axi_value_checks_seen
        seq = smc_gpio_filter_access_sep_test_seq("gpio_filter_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

        # The allow/deny proof is in the sequence: each denied access is compared
        # against the AXI DECERR encoding and the error-slave data signature, and
        # each allowed access carries an `expected=` the scoreboard enforces.
        # None of that is restated here.
        #
        # This gate carries a quantity the sequence does not produce -- the
        # number of exact rdata compares the SCOREBOARD booked on its own
        # analysis path, incremented only after `got == exp` passed. A leg that
        # lost its `expected=`, or an analysis port that came unbound, drops the
        # delta below the floor and fails here while every sequence-side assert
        # still passes.
        _EXPECTED_VALUE_CHECKS = 4  # GPIO0 pre / priv / priv-write readback, GPIO1 priv
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
