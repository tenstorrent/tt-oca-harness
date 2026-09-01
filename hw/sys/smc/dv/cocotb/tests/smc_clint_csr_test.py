# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS cluster CLINT MTIME/MSIP CSR test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_clint_csr_test_seq import MSIP_NUM, smc_clint_csr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clint_csr_test(smc_base_test):
    """MTIME advances and MSIP is per-hart writable, over SEP_IN."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clint_csr_test_seq("clint_csr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.mtime_second > seq.mtime_first, (
            f"CLINT MTIME 0x{seq.mtime_first:016x} -> 0x{seq.mtime_second:016x}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor, literal here and NOT read from
            # `seq.accesses`: 2 MTIME reads + 4 MSIP reset reads + 4 writes +
            # 4 readbacks + 4 restores + 4 restore readbacks.
            min_csr_accesses=2 + MSIP_NUM * 5,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "Cluster CLINT over SEP_IN: MTIME strictly increased between "
                "two reads (also the reachability proof -- a bit-27 fold onto "
                "the CORE0 WDT window, the shape #1237 documents for the BEU, "
                "could not increment), and MSIP held an alternating per-hart "
                "pattern read back with all four resident"
            ),
        )
