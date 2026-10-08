# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_sysreset_stop_clks_test - dtp_stop_clks_o across a primary reset.

SMU_RESET_029 (smu_dtp_sysreset_stop_clks_test), steps S1-S3, checkers CHK-DTP-SYSRESET-S1..S2.
Spec: hw/sys/dtp/doc/clk_rst.adoc (Clock Stop, Reset Architecture), hw/sys/smu/doc/port_table.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_dtp_sysreset_stop_clks_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_sysreset_stop_clks_test_seq import smu_dtp_sysreset_stop_clks_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_sysreset_stop_clks_test(smu_base_test):
    """dtp_stop_clks_o reads 0 inside a primary reset and returns three cycles after release."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_dtp_sysreset_stop_clks_test_seq(self).run()
