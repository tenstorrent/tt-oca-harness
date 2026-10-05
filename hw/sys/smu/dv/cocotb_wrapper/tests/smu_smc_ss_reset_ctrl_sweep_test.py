# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_ss_reset_ctrl_sweep_test - the SS reset-control lanes end to end.

Walks the seven SMC reset-unit registers that own the fields of
``ss_reset_ctrl_o`` through a lane-signature pattern set and back to their RDL
reset values, comparing the boundary word the testbench assembles from
``ss_reset_ctrl_o[i].<field>`` against the CSR read-back at every step, and
requiring the ``SS_COLD_RESET_LOCK`` woset bit to block its own lane while the
rest of the write lands. Every bit of all 32x7 fields is observed both rising
and falling.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_ss_reset_ctrl_sweep_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_ss_reset_ctrl_sweep_seq import smu_smc_ss_reset_ctrl_sweep_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_ss_reset_ctrl_sweep_test(smu_base_test):
    """Subsystem reset-control registers proved lane for lane at ``ss_reset_ctrl_o``."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_ss_reset_ctrl_sweep_seq(self).run()
