# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TB-glue: DBS capture latch demo (NOT DUT DFD RTL).

DEFERRED from green (2026-07-29): tb_dfd_fault_inject only latches a
hardcoded token 0xDB5C_AFE1. Real DFD lives under smc_dfd_wrap / hw/ip/dfd.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_dfd_dbs_fault_inject_test_seq import (
    smc_dfd_dbs_fault_inject_test_seq,
)


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
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "TB_GLUE only: tb_dfd_fault_inject latched 0xDB5C_AFE1 "
                "(not DUT DFD RTL)"
            ),
        )
