# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_inbound_window_sweep_test - ext_in into the SMC peripheral windows.

Every AxPROT into the eFuse shim word, the SMC external target and a DTP
control register; every AxSIZE and low address bit into the external target;
and a write train under sixteen AWIDs into the SMC SPM.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_inbound_window_sweep_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_inbound_window_sweep_test_seq import smu_smc_inbound_window_sweep_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_inbound_window_sweep_test(smu_base_test):
    """Inbound SMN traffic into the SMC shim, external and DTP windows; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_inbound_window_sweep_test SMC windows")
        seq = smu_smc_inbound_window_sweep_test_seq(self)
        await seq.run()
        assert all(seq.steps.values()), f"window sweep incomplete {seq.steps}"
