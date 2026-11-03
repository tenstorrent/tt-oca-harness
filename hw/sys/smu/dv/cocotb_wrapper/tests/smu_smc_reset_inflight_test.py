# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_012 ANCHOR: smu_smc_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 9 RECORD-SHA256: 226ef1b275ecc7000c72ff4359e28212e392d704cc90a7d4f0dcd90d6f3b16f5
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 11 ENV: cocotb
"""smu_smc_reset_inflight_test - SMC-side resets with crossbar traffic in flight.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_reset_inflight_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_reset_inflight_test_seq import smu_smc_reset_inflight_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_reset_inflight_test(smu_base_test):
    """SMC warm, cool, FLR, core and uncore resets with ext_in, smc_out and SEP traffic."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_reset_inflight_test SEP=1 ext_in -> smc_in")
        seq = smu_smc_reset_inflight_test_seq(self)
        await seq.run()
        assert seq.done, f"SMC reset in-flight scenario incomplete steps={seq.steps}"
