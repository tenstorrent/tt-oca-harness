# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-1 / P2-7 scratch ECC codeword corrupted in the macro array: one flipped bit is benign."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_ecc_codeword_corrupt_test_seq import (
    smc_ecc_codeword_corrupt_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ecc_codeword_sec_test(smc_base_test):
    """One flipped codeword bit: the CPU reads the bank and DED stays low."""

    required_evidence = ("CHK-ECC-CODEWORD-SEC",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_codeword_corrupt_test_seq(
            "ecc_codeword_sec_seq", poke_mask=0b01, expect_ded=False
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            # No CSR stimulus: the codeword is poked backdoor and the
            # property is read from tb_cluster_ded_seen, asserted in the
            # sequence. Booked as an activity stamp so it is not counted
            # as a protocol VIP check it cannot be.
            auto_evidence=True,
            proxy=False,
            details="scratch bank0 codeword ^= 1 bit before boot; scratch reads advance with cluster_ded held at 0",
        )
