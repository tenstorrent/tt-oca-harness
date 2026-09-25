# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Requests that reach a register block while one of its external registers is busy.

On six register blocks with an external register: one outstanding group that
opens with a side-effect-free access to the external register and follows it
at once with a read and a write of the block's probe, so both arrive while the
external access is pending. Every held-back request must be answered, the
probe read must return the value the block held, and the probe must keep it.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpuif_external_stall_test_seq import smc_cpuif_external_stall_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 6 blocks at 7 SEP_IN AXI accesses each -- the held probe read, the group of
# two external reads, two probe reads and a probe write, and the closing probe
# read -- plus the LSR read after the UART's.
CPUIF_EXTERNAL_STALL_MIN_CSR_ACCESSES = 6 * 7 + 1


@pyuvm.test()
class smc_cpuif_external_stall_test(smc_base_test):
    """Present requests while each block's external register is pending."""

    required_evidence = ("CHK-CPUIF-EXTERNAL-STALL",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpuif_external_stall_test_seq("smc_cpuif_external_stall_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=CPUIF_EXTERNAL_STALL_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{seq.blocks} register blocks stalled on an external access",
        )
