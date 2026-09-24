# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract write sweep of the CLA MMR block over SEP_IN AXI.

Drives every software-owned register of the CLA sub-block of the SMC_CLA
aperture through a half-register write cycle and restores each one to its
generated RDL reset.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_mmr_sweep_test_seq import smc_dfd_cla_mmr_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 77 software-owned CLA MMR registers (78 in the generated map, less
# CDbgClaCtrlStatus), 9 accesses each: the reset read, then for each of the ones
# and restore patterns a low-half write, a readback, a high-half write and a
# readback. No polling, every leg directed.
CLA_MMR_SWEEP_MIN_CSR_ACCESSES = 77 * 9


@pyuvm.test()
class smc_dfd_cla_mmr_sweep_test(smc_base_test):
    """Sweep every software-owned CLA MMR field against its RDL contract."""

    required_evidence = ("CHK-CLA-MMR-WRITE-SWEEP",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_mmr_sweep_test_seq("cla_mmr_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_MMR_SWEEP_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.registers_swept} CLA MMR registers swept against the generated "
                f"RDL map, {seq.value_checks} value compares"
            ),
        )
