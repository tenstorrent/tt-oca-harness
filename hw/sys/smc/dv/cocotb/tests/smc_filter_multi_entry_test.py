# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap round 2: filter 16 inbound + 16 outbound CONFIG sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_multi_entry_test_seq import smc_filter_multi_entry_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_multi_entry_test(smc_base_test):
    """P1 coverage-gap round 2: filter 16 inbound + 16 outbound CONFIG sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_multi_entry_test_seq("smc_filter_multi_entry_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap round 2: filter 16 inbound + 16 outbound CONFIG sweep",
        )
