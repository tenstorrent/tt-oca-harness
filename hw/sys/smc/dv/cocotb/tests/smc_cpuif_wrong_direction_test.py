# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register blocks accessed in the direction their contract does not define.

Writes at read-only registers, reads of write-only ones, and reads of the few
registers no leaf reads, across eleven register blocks. Each write must be
answered and take no effect, each write-only read must return zero, and each
block's probe register must read the same value around its accesses.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpuif_wrong_direction_test_seq import smc_cpuif_wrong_direction_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 40 targets at one access at least, plus the before/after probe reads that
# bracket each of the 11 blocks (22). Every write carries two further reads --
# the register or its FIFO level either side -- except the two free-running
# timer counters, so the real count is higher; the floor counts the minimum.
CPUIF_WRONG_DIRECTION_MIN_CSR_ACCESSES = 40 + 22


@pyuvm.test()
class smc_cpuif_wrong_direction_test(smc_base_test):
    """Write read-only registers, read write-only ones, and read the unread."""

    required_evidence = (
        "CHK-CPUIF-READ-WRITE-ONLY",
        "CHK-CPUIF-WRITE-READ-ONLY",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpuif_wrong_direction_test_seq("smc_cpuif_wrong_direction_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=CPUIF_WRONG_DIRECTION_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.writes_ignored} ignored writes, {seq.reads_zero} zero reads, "
                f"{seq.plain_reads} plain reads, {seq.blocks_guarded} blocks guarded"
            ),
        )
