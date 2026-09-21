# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_boundary_lane_sweep_test - every lane of the SMC-facing wrapper buses.

Extends what smu_smc_boundary_io_test proves on one or two lanes to all of
them: the 256 external interrupt lanes on the SMC CPU interrupt vector, the
32 isolation-request and 32 subsystem-configuration lanes of the reset unit,
the 32 outbound mailbox interrupt lanes, the 65 GPIO pads on their interrupt
and DATA_CTRL.PAD2CORE mirrors, and the four UART interrupt lanes. Each lane
is driven both ways, each compare reads a DUT-produced value, and each
aggregate names the lane count it expects.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_boundary_lane_sweep_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_boundary_lane_sweep_seq import smu_smc_boundary_lane_sweep_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_boundary_lane_sweep_test(smu_base_test):
    """Per-lane sweep of the multi-lane SMC-facing wrapper boundary buses."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_boundary_lane_sweep_seq(self).run()
