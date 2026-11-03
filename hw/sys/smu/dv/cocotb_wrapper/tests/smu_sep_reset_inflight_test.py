# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMU_SEP_SCN_011 ANCHOR: smu_sep_reset_inflight_test
# DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: f3f66a20f44e7f77f94138ab59ec1cabcacf092a44bd8bb36194e38ec7e84132
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_SEP_SCN_VPLAN_DETAIL_RESET.md @ artifact_revision 5 ENV: cocotb
"""smu_sep_reset_inflight_test - SEP-side resets with crossbar traffic in flight.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_reset_inflight_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_reset_inflight_test_seq import smu_sep_reset_inflight_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_reset_inflight_test(smu_base_test):
    """SW_RESET_N, JTAG sep_reset_n and watchdog-bite resets with ext_in and sep_out outstanding."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_reset_inflight_test SEP=1 ext_in -> sep_in")
        seq = smu_sep_reset_inflight_test_seq(self)
        await seq.run()
        assert seq.done, f"SEP reset in-flight scenario incomplete steps={seq.steps}"
