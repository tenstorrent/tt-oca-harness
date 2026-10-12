# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CFG_0, AVS_CFG_1 and AVS_CONFIG behaviour across the AVSBus CDC bridge.

Contract SMC_CLOCK_SRC_015, anchor smc_avs_cfg_csr_cdc_test.
Scenarios CSRC-AVS-CSR.S1..S5 and CSRC-CDC-AVS.S1..S3 at the default clock triple.
Sources: hw/ip/avsbus_controller/regs/avsbus_controller.rdl, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avs_cfg_csr_cdc_test_seq import smc_avs_cfg_csr_cdc_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avs_cfg_csr_cdc_test(smc_base_test):
    """AVS_CFG_1 and AVS_CONFIG resets, fields, strobes, pulse and ordering."""

    required_evidence = (
        "CHK-AVS-CSR-RESET",
        "CHK-AVS-CSR-FIELDS",
        "CHK-AVS-CSR-BYTE-LANE-2",
        "CHK-AVS-CSR-FORCE-PULSE",
        "CHK-AVS-CSR-UNALLOCATED",
        "CHK-CDC-AVS-RT",
        "CHK-CDC-AVS-ORDER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avs_cfg_csr_cdc_test_seq("avs_cfg_csr_cdc_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
