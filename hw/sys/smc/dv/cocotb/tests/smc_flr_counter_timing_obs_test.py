# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Measure the FLR cool-reset pre-delay and hold counters in clk_ref_i cycles.

Source hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl; #3423 asks for the counter clock and
offset to be stated, and the leaf is held out of `all` until it is ruled.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_flr_counter_timing_obs_test_seq import smc_flr_counter_timing_obs_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   the idle read of ISOLATE_REQ_SMC_REG                                      1
#   nine legs: two counters written and read back, one post read, one clear
#   and at least one poll                                                    63
#   both counters cleared and read back                                       4
FLR_COUNTER_TIMING_OBS_MIN_CSR_ACCESSES = 68


@pyuvm.test()
class smc_flr_counter_timing_obs_test(smc_base_test):
    """FLR counters measured on clk_ref_i for N in {1,2,3,8} x M in {1,4}, plus a second edge."""

    required_evidence = ("CHK-FLR-COUNTER-TIMING-OBS",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_flr_counter_timing_obs_test_seq("smc_flr_counter_timing_obs_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=FLR_COUNTER_TIMING_OBS_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{len(seq.rows)} FLR counter legs measured on clk_ref_i",
        )
