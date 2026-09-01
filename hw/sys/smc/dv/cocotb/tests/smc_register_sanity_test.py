# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM register sanity test (Batch B).

After base bring-up, drives real SYS AXI read/write/readback traffic to SMC
scratch CSRs through the public tb_top ``s_axi_*`` bridge.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_register_sanity_test_seq import smc_register_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_register_sanity_test(smc_base_test):
    """Run the SMC OSS register-sanity scenario."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_register_sanity_test_seq("register_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Field-aware catalog scratch RW write/read/restore checked",
        )
