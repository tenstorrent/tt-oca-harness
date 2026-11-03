# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag2axi_access_matrix_rand_test - drawn cells of the three DTP JTAG2AXI bridges.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_jtag2axi_access_matrix_rand_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_jtag2axi_access_matrix_rand_test_seq import (
    smu_jtag2axi_access_matrix_rand_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_jtag2axi_access_matrix_rand_test(smu_base_test):
    """Drawn address, size, strobe, payload, series and sticky cells over the DTP bridges."""

    use_shared_env = True
    # An SMC JTAG2AXI SERIES write needs TCK at least four clk_smu periods.
    min_jtag_smu_ratio = 4.0
    required_evidence = (
        "CHK-J2AMX-ADDR",
        "CHK-J2AMX-DATA",
        "CHK-J2AMX-SERIES",
        "CHK-J2AMX-SIZE",
        "CHK-J2AMX-STICKY-DRAWN",
        "CHK-J2AMX-WSTRB",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_jtag2axi_access_matrix_rand_test SEP=1 JTAG")
        seq = smu_jtag2axi_access_matrix_rand_test_seq(self)
        await seq.run()
        assert seq.done, "JTAG2AXI access matrix scenario incomplete"
