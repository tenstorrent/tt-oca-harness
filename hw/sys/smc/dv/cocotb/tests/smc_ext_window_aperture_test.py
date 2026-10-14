# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_ext_window_aperture_test: external window and REGION_SIZE aperture."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_window_aperture_test_seq import smc_ext_window_aperture_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_window_aperture_test(smc_base_test):
    """Window reads and writes reach the external port; REGION_SIZE limits the window."""

    required_evidence = (
        "CHK-EXT-READ-REQ",
        "CHK-EXT-WRITE-REQ",
        "CHK-EXT-SHIM-ISOLATION",
        "CHK-EXT-REGION-DECERR",
        "CHK-EXT-INFLIGHT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_window_aperture_test_seq("ext_window_aperture_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
