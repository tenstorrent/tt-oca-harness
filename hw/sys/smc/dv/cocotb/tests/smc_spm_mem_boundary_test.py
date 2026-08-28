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
        # `lo_ok`/`mid_ok`/`hi_ok` now carry the WORDS read back, not flags, so
        # `assert a and b and c` would only be testing that three non-zero
        # patterns are non-zero. The scoreboard already enforces each word
        # against its own `expected=`, and asserting the three are distinct
        # would be implied by those three exact compares -- the same
        # dominated-assert trap this campaign has been removing.
        #
        # What is NOT implied, and is what this gate checks: that all three
        # readbacks happened at all. A body that returned early, or a future
        # refactor that dropped an edge, fails here.
        observed = (seq.lo_ok, seq.mid_ok, seq.hi_ok)
        assert all(v is not None for v in observed), (
            f"spm boundary did not read back every edge: lo={seq.lo_ok} "
            f"next={seq.mid_ok} hi={seq.hi_ok}"
        )
