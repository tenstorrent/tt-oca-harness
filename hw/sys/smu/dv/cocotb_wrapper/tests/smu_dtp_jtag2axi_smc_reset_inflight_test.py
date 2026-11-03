# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_013 ANCHOR: smu_dtp_jtag2axi_smc_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: b0c97d3966fed33fbf0796b2fc3f3393c65c9632c843d61d61a3b78cdec78e5d
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 3 ENV: cocotb
"""smu_dtp_jtag2axi_smc_reset_inflight_test - DTP JTAG2AXI into the SMC fabric across SMC resets.

JTAG2AXI SINGLE_OP accesses launched inside a pin cool reset, an FLR-timed cool reset and a
CORE0 watchdog warm reset, and across the release of the pin; the values read after the
resets and a fresh access.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_dtp_jtag2axi_smc_reset_inflight_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_smc_reset_inflight_test_seq import (
    smu_dtp_jtag2axi_smc_reset_inflight_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_smc_reset_inflight_test(smu_base_test):
    """JTAG2AXI accesses during and across SMC cool, FLR and warm resets."""

    use_shared_env = True
    required_evidence = (
        "CHK-J2A-RV-BASELINE",
        "CHK-J2A-DURING-COOL",
        "CHK-J2A-MID-RELEASE",
        "CHK-J2A-POST-RESET-VALUES",
        "CHK-J2A-FRESH-ACCESS",
        "CHK-J2A-DURING-WARM",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_jtag2axi_smc_reset_inflight_test JTAG2AXI-SMC-RESET SEP=1 JTAG"
        )
        seq = smu_dtp_jtag2axi_smc_reset_inflight_test_seq(self)
        await seq.run()
        assert seq.done, "jtag2axi_smc_reset_inflight scenario incomplete"
