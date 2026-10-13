# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_cpu_ctrl_boot_state_test — CPU_CTRL reset-state registers over JTAG2AXI."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_cpu_ctrl_boot_state_test_seq import smu_smc_cpu_ctrl_boot_state_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_cpu_ctrl_boot_state_test(smu_base_test):
    """CPU_CTRL reset vectors, reset control, watchdog, scratch, attributes and dummy ROM."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_cpu_ctrl_boot_state_test SMU_SMC_BOOT_008 SEP=1 J2A"
        )
        seq = smu_smc_cpu_ctrl_boot_state_test_seq(self)
        await seq.run()
        assert seq.done, "cpu_ctrl boot state scenario incomplete"
