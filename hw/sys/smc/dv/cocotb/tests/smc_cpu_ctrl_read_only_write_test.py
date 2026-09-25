# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes at the CPU_CTRL registers software cannot write.

Writes all ones at TEST_CTRL, SMC_ATTRIBUTES and the head of each per-core
writeback program counter array and requires each to read the same word
afterwards, then writes 0 full width into the singlepulse fields of
WDT_TIMEOUT_RESET and requires the core reset pulse count not to move.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpu_ctrl_read_only_write_test_seq import (
    smc_cpu_ctrl_read_only_write_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   6 read-only registers x (read, write, read)                             18
#   WDT_TIMEOUT_RESET: the pulse count read, the write of 0, the readback
#     and the second pulse count read                                        4
#   4 MUTEX registers x (four acquiring reads, two half writes while held,
#     a full write carrying a one, two half writes while free, the release) 40
CPU_CTRL_READ_ONLY_WRITE_MIN_CSR_ACCESSES = 6 * 3 + 4 + 4 * 10


@pyuvm.test()
class smc_cpu_ctrl_read_only_write_test(smc_base_test):
    """Write at every CPU_CTRL address the RDL makes read-only."""

    required_evidence = (
        "CHK-CPU-CTRL-MUTEX-HALF-WRITE",
        "CHK-CPU-CTRL-READ-ONLY-WRITE",
        "CHK-CPU-CTRL-WDT-ZERO-WRITE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_read_only_write_test_seq("smc_cpu_ctrl_read_only_write_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=CPU_CTRL_READ_ONLY_WRITE_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.read_only_registers} read-only registers written at, core reset "
                f"pulse count {seq.pulse_count_before} -> {seq.pulse_count_after}"
            ),
        )
