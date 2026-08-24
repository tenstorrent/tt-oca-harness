# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPM window edges over SEP_IN AXI."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_spm_mem_boundary_test_seq import smc_spm_mem_boundary_test_seq


@pyuvm.test()
class smc_spm_mem_boundary_test(smc_base_test):
    """SPM first/next/last 64-bit word write/readback via SEP_IN AXI."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_mem_boundary_test_seq("spm_mem_boundary_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.lo_ok and seq.mid_ok and seq.hi_ok, (
            f"spm boundary incomplete lo={seq.lo_ok} next={seq.mid_ok} hi={seq.hi_ok}"
        )
