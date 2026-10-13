# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_sram_init_sequence_test - scratchpad zero-fill completion across two cold boots.

Contract SMU_SMC_BOOT_005, anchor smu_smc_sram_init_sequence_test.
Spec: hw/sys/smc/doc/cpu.adoc Reset and Boot; hw/sys/smu/doc/port_table.adoc
smc_init_mem_done_o row. On the `--dut smu` wrapper under sep_rtl with the automatic
initialization enabled, smc_init_mem_done_o rises once after the last scratch write, no ROM read
precedes it, and a second cold reset re-arms it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_sram_init_sequence_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_sram_init_sequence_test_seq import (
    smu_smc_sram_init_sampler,
    smu_smc_sram_init_sequence_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_sram_init_sequence_test(smu_base_test):
    """smc_init_mem_done_o rises once per cold boot after the zero-fill and before the ROM fetch."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Arm the sampler, then run the shared bring-up that contains the first done rise."""
        self.sampler = smu_smc_sram_init_sampler()
        self.sampler.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_smc_sram_init_sequence_test_seq(self).run()
