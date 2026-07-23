# SPDX-License-Identifier: Apache-2.0
"""SMC OSS CPU-control CSR path precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_to_sep_axi_test_seq import smc_cpu_to_sep_axi_test_seq
from seq_lib.smc_cpu_vip_utils import check_cpu_bfm_observability


@pyuvm.test()
class smc_cpu_to_sep_axi_test(smc_base_test):
    """Run the CPU-control to SEP-facing CSR reachability precheck."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_to_sep_axi_test_seq("cpu_to_sep_axi_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="SEP_IN AXI master-BFM CPU-control to SEP-facing path checked",
        )
