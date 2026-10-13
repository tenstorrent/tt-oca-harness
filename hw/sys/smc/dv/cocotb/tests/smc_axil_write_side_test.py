# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Downstream AXI-Lite write-side traffic and the idle windows after reset and a burst.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_axil_write_side_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axil_write_side_test_seq import (
    EXPECTED_ACCESSES,
    smc_axil_write_side_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axil_write_side_test(smc_base_test):
    """Alternate eFuse-shim and external-window writes, then check the idle windows."""

    required_evidence = (
        "CHK-AXLWS-PROBE-ALIVE",
        "CHK-AXLWS-IDLE-AFTER-RESET",
        "CHK-AXLWS-WRITE-INTERLEAVE",
        "CHK-AXLWS-MIXED-RDWR",
        "CHK-AXLWS-EXT-WRITE-PENDING",
        "CHK-AXLWS-IDLE-AFTER-BURST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    async def run_scenario(self) -> None:
        seq = smc_axil_write_side_test_seq("axil_write_side_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == EXPECTED_ACCESSES, (
            f"{seq.accesses} SEP_IN accesses issued, want {EXPECTED_ACCESSES}"
        )
