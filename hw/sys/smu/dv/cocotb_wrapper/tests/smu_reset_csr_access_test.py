# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_reset_csr_access_test - reset values, access behaviour and sync_irq_o of the reset CSRs.

Steps S1-S9,
checkers CHK-CSR-RESET-VALUES-S2..S4, CHK-CSR-ACCESS-S1..S3 and CHK-SYNC-IRQ-S1..S2.
Spec: hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl,
hw/sys/smc/regs/blocks/ndm_reset/ndm_reset.rdl, hw/sys/smc/doc/clk_rst.adoc,
hw/sys/smu/doc/port_table.adoc, doc/integrator/src/smu-smc.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_reset_csr_access_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_reset_csr_access_test_seq import smu_reset_csr_access_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_reset_csr_access_test(smu_base_test):
    """Reset-unit and NDM CSR reset values, access rules and the sync_irq_o path."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_reset_csr_access_test_seq(self).run()
