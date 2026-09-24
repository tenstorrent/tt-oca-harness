# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract write sweep of the DST, sink and funnel MMR blocks.

Writes every register of the `dst`, `dst_sink` and `funnel` sub-blocks of the
SMC_CLA aperture with every bit its fields declare, holds each read to the
parts of the contract the RDL pins, and restores every register. No trace runs,
so the enables it writes have nothing to act on.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_sink_mmr_sweep_test_seq import smc_dfd_sink_mmr_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 24 registers (6 dst, 13 dst_sink, 5 funnel), 5 accesses each: the reset read,
# the pattern write, its readback, the restore write and its readback. No
# polling, every leg directed.
#
# Two adjacent pairs get a further double-width pass: two reset reads, the
# pair write and two readbacks, the restore and two more readbacks.
SINK_MMR_SWEEP_MIN_CSR_ACCESSES = 24 * 5 + 2 * 8


@pyuvm.test()
class smc_dfd_sink_mmr_sweep_test(smc_base_test):
    """Write every DST, sink and funnel MMR against its RDL contract and restore it."""

    required_evidence = (
        "CHK-DFD-SINK-MMR-DECODE",
        "CHK-DFD-SINK-MMR-PAIR",
        "CHK-DFD-SINK-MMR-READONLY",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_sink_mmr_sweep_test_seq("sink_mmr_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=SINK_MMR_SWEEP_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.registers_swept} registers swept, {seq.pinned_registers} with a "
                f"pinned readback, {seq.value_checks} value compares"
            ),
        )
