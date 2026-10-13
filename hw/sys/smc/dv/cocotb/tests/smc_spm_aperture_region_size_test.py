# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad window reach by aperture alias and REGION_SIZE over SEP_IN AXI."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_aperture_region_size_test_seq import smc_spm_aperture_region_size_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_spm_aperture_region_size_test(smc_base_test):
    """Local alias, global aperture and REGION_SIZE limits on one scratchpad word."""

    required_evidence = (
        "CHK-SPM-ALIAS",
        "CHK-SPM-REGION-REACH",
        "CHK-SPM-REGION-DECERR",
        "CHK-SPM-REGION-B2B",
        "CHK-SPM-REGION-INFLIGHT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_aperture_region_size_test_seq("spm_aperture_region_size_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
