# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_series_contention_test — SMC fabric JTAG2AXI series data and contention."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_series_contention_test_seq import (
    smu_dtp_jtag2axi_series_contention_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_series_contention_test(smu_base_test):
    """SERIES INCR, NO_INCR and error-status data, pipeline depth, sticky op and SINGLE_OP busy."""

    use_shared_env = True
    # An SMC JTAG2AXI SERIES write needs TCK at least four clk_smu periods.
    min_jtag_smu_ratio = 4.0
    required_evidence = (
        "CHK-DBG-J2A-BUSY-OP3",
        "CHK-DBG-J2A-SERIES-ERRSTATUS",
        "CHK-DBG-J2A-SERIES-INCR",
        "CHK-DBG-J2A-SERIES-NOINCR",
        "CHK-DBG-J2A-SERIES-PIPELINE",
        "CHK-DBG-J2A-SERIES-SETUP",
        "CHK-DBG-J2A-SINGLE-INDEP",
        "CHK-DBG-J2A-STICKY-DECERR-FIRST",
        "CHK-DBG-J2A-STICKY-RESET",
        "CHK-DBG-J2A-STICKY-SLVERR-FIRST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_jtag2axi_series_contention_test SEP=1 JTAG")
        await smu_dtp_jtag2axi_series_contention_test_seq(self).run()
