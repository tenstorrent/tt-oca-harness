# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sram_auto_init_done_test - SRAM auto-initialization completion.

Closes SMU-MEMINIT.S1 against the smc_disable_sram_auto_init_i and smc_init_mem_done_o
rows of port_table.adoc, on the `--dut smu` production wrapper built with
compile_smu_chiplet and no +smc_scratch_ram_hex image: with
smc_disable_sram_auto_init_i read low at the SMU boundary and smc_init_mem_done_o
read high after the bring-up sweep, a cold reset clears smc_init_mem_done_o, the
SMC scratch-RAM zeroing is then seen running at its consumer (enable high,
address counter advancing, writes reaching the scratch RAM) and
smc_init_mem_done_o asserts again and holds once it completes.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sram_auto_init_done_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sram_auto_init_done_seq import smu_sram_auto_init_done_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sram_auto_init_done_test(smu_base_test):
    """smc_init_mem_done_o after the default SRAM auto-initialization."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_sram_auto_init_done_seq(self).run()
