# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Observe a second CTRL_STATUS trigger while the zeroer is busy (issue and drain windows).

Sources hw/sys/smc/doc/zeroer.adoc, hw/ip/zeroer/regs/zeroer_ctrl.rdl; #3422 asks for the
busy-trigger rule, and the leaf is held out of `all` until it is ruled.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_busy_trigger_obs_test_seq import smc_zeroer_busy_trigger_obs_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   6 output-fabric pass-all filter writes                                   6
#   DEST_ADDR, SIZE and start writes of four jobs                           12
#   one STATUS read before, and one after each phase                         3
ZEROER_BUSY_TRIGGER_OBS_MIN_CSR_ACCESSES = 21


@pyuvm.test()
class smc_zeroer_busy_trigger_obs_test(smc_base_test):
    """Second trigger in ST_ISSUE_* and in ST_IDLE-with-outstanding; effect reported, not graded."""

    required_evidence = ("CHK-ZEROER-BUSY-TRIGGER-OBS",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_busy_trigger_obs_test_seq("smc_zeroer_busy_trigger_obs_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_BUSY_TRIGGER_OBS_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="zeroer busy-trigger observation phases completed",
        )
