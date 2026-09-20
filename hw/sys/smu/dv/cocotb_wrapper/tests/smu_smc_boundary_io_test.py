# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_boundary_io_test - SMC-facing boundary signals against their CSRs.

Exercises the SMC side of the wrapper boundary that port_table.adoc declares
but no leaf drove: the NDM reset request/process pair, an external interrupt
lane, the reset-unit terminations (SS_CONFIG, SYNC_REG, ISOLATE_REQ_REG), the
two DFT abort status pins, and the FLR isolation path that raises both
isolate_req_o and skip_mem_repair_o. Each leg compares a DUT-produced value --
an SMC CSR read, the boundary output, or the SMC CPU interrupt vector bit the
interrupt spec assigns to the pin -- against the contract, never against the
value the bench drove.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_boundary_io_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_boundary_io_seq import smu_smc_boundary_io_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_boundary_io_test(smu_base_test):
    """SMC boundary inputs and outputs proved through the SMC register map and interrupt vector."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_boundary_io_seq(self).run()
