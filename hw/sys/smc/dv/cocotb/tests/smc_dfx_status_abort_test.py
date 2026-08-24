# SPDX-License-Identifier: Apache-2.0
"""DFX STATUS_SMU abort pins. Not DEBUG_CTRL reset reads."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_dfx_status_abort_test_seq import smc_dfx_status_abort_test_seq


@pyuvm.test()
class smc_dfx_status_abort_test(smc_base_test):
    """mem_repair_abort / mbist_abort → STATUS_SMU sticky bits."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_status_abort_test_seq("dfx_status_abort_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.repair_ok and seq.mbist_ok, (
            f"DFX abort incomplete idle={seq.idle_ok} "
            f"repair={seq.repair_ok} mbist={seq.mbist_ok}"
        )
