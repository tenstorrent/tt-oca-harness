# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS deadspace-decode test (#214 wrap-to-live class)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_deadspace_decode_test_seq import smc_deadspace_decode_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_deadspace_decode_test(smc_base_test):
    """Probe wrap-period offsets past PeakRDL SIZE and watch live CSRs."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_deadspace_decode_test_seq("deadspace_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "Deadspace wrap-to-live probes "
                f"(wrap={len(seq.wrap_to_live)} alias={len(seq.read_alias)} "
                f"accepted={len(seq.accepted_dead)} refused={len(seq.refused)})"
            ),
        )
