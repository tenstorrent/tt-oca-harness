# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: tb_glue
TB-glue only: `tb_dfd_fault_inject` latches the hardcoded token 0xDB5C_AFE1;
the DUT DFD RTL (smc_dfd_wrap / hw/ip/dfd) is not exercised.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_dbs_fault_inject_test_seq import (
    smc_dfd_dbs_fault_inject_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_dbs_fault_inject_test(smc_base_test):
    """TB capture latch demo — not smc_dfd_wrap / dfd_top coverage."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_dbs_fault_inject_test_seq("dfd_dbs_fault_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: the single VERSION_LO CSR read this
            # TB-glue scenario issues. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=1,
            csr_accesses=seq.accesses,
            proxy=False,
            details=("TB_GLUE only: tb_dfd_fault_inject latched 0xDB5C_AFE1 (not DUT DFD RTL)"),
        )
