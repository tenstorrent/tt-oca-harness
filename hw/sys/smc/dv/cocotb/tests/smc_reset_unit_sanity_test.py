# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""COLD vs COLD_WARM across SEP WDT."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_reset_unit_sanity_test_seq import smc_reset_unit_sanity_test_seq


@pyuvm.test()
class smc_reset_unit_sanity_test(smc_base_test):
    """COLD scratch persists a SEP WDT pulse; COLD_WARM does not."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_unit_sanity_test_seq("reset_unit_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The verdict is the sequence's. Its fail-capable content is the
        # `expected=`-bearing scratch and SS_* readbacks (scoreboard-enforced),
        # `_await_warm_cleared`'s bounded poll, and the CSR-to-pin comparison
        # against `tb_isolate_req_o`. A flag set at the end of a straight-line
        # body cannot add a failure mode ([NO-ALWAYS-PASS-CHECKER]), so none is
        # kept here.
        #
        # The line below is a ZERO-ACTIVITY GUARD, not a DUT check: it catches a
        # sequence body that issued no register sweep at all
        # ([NO-ZERO-ACTIVITY-PASS]).
        assert seq.ss_regs_swept, (
            "the RESET_UNIT SS_* write/readback sweep issued no stimulus in "
            "this run"
        )
