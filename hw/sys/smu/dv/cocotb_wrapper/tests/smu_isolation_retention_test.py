# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_isolation_retention_test - isolation registers and FLR counters across cool and cold reset.

Steps S1-S5, checkers CHK-ISO-RETAIN-S1..S4.
Spec: hw/sys/smc/doc/clk_rst.adoc (Isolation Controls, Isolation Connections, Timing and Recovery).

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_isolation_retention_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_isolation_retention_test_seq import smu_isolation_retention_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_isolation_retention_test(smu_base_test):
    """Isolation registers and FLR counters survive cool reset and clear on stable cold reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_isolation_retention_test_seq(self).run()
