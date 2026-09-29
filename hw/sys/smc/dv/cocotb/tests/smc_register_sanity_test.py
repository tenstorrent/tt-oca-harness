# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM register sanity test.

After base bring-up, drives real SYS AXI read/write/readback traffic to SMC
scratch CSRs through the public tb_top ``s_axi_*`` bridge.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_register_sanity_test_seq import smc_register_sanity_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks
# together with a sequence that silently stopped issuing accesses, which is
# exactly the failure the floor exists to catch.
# Composition (smc_register_sanity_test_seq, directed, no polling): the sequence
# walks 3 scratch CSRs (SCRATCH_COLD_0, SCRATCH_COLD_1, SCRATCH_COLD_WARM_0 in
# WRITE_READBACK) and issues 5 accesses on each --
#   reset read + pattern write + pattern readback + restore write + restore
#   readback
#   => 3 x 5 = 15 SEP_IN AXI accesses
REGISTER_SANITY_MIN_CSR_ACCESSES = 15


@pyuvm.test()
class smc_register_sanity_test(smc_base_test):
    """Run the SMC OSS register-sanity scenario."""

    required_evidence = ("CHK-CSR-SCRATCH-RW-RESTORE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_register_sanity_test_seq("register_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=REGISTER_SANITY_MIN_CSR_ACCESSES,
            proxy=False,
            details="Field-aware catalog scratch RW write/read/restore checked",
        )
