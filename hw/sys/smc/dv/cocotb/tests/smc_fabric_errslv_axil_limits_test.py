# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The FIFO-bounded fabric limits withhold the read past their stated number.

Spec source: fabric.adoc SMC Fabric Transaction Limits.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fabric_errslv_axil_limits_test_seq import (
    smc_fabric_errslv_axil_limits_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fabric_errslv_axil_limits_test(smc_base_test):
    """RREADY-held read groups past ErrSlvMaxTrans and the AXI-Lite crossbar limit of 4."""

    required_evidence = (
        "CHK-AXIL-XBAR-5TH-WAITS",
        "CHK-ERRSLV-33RD-WAITS-FOR-RETIRE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_fabric_errslv_axil_limits_test_seq("smc_fabric_errslv_axil_limits_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.raise_fails()
