# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap Round 5: DFT_CTRL status decode."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_dft_ctrl_test_seq import smc_dft_ctrl_test_seq


@pyuvm.test()
class smc_dft_ctrl_test(smc_base_test):
    """P1 coverage-gap depth: top-level DFT_CTRL status (0xC000_F800)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dft_ctrl_test_seq("smc_dft_ctrl_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="P1 coverage-gap R5: DFT_CTRL STATUS_SMU bounded decode",
        )
