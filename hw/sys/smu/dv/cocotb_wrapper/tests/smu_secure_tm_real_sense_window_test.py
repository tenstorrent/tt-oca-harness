# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_secure_tm_real_sense_window_test - secure_tm_o across a real SEP fuse sense.

Contract SMU_SEP_006, anchor smu_secure_tm_real_sense_window_test.
Spec: hw/sys/sep/doc/test_mode.adoc, hw/sys/sep/doc/lifecycle_controller.adoc,
doc/integrator/src/smu.adoc, hw/sys/smu/doc/port_table.adoc, hw/ip/efuse/doc/interface.adoc.

Runs under sep_rtl_fuse_sense: the SEP eFuse bank model answers a real sense, with
secure_tm_req_i held at 1 from before the first cold reset.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_secure_tm_real_sense_window_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_fuse_sense_probe import SmuFuseSenseProbe, sep_command_nets
from seq_lib.smu_secure_tm_real_sense_window_test_seq import (
    smu_secure_tm_real_sense_window_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_secure_tm_real_sense_window_test(smu_base_test):
    """secure_tm_o is cleared by cold reset and ignores the strap before the sampling event."""

    use_shared_env = True

    def drive_idle_inputs(self) -> None:
        super().drive_idle_inputs()
        cocotb.top.tb_secure_tm_req.value = 1

    async def bring_up(self) -> None:
        dut = cocotb.top
        self.fuse_probe = SmuFuseSenseProbe(
            self,
            edge_signals={"sep_fuse_sense_done_o": dut.sep_fuse_sense_done_o},
            command_nets={"sep_efuse_shim": sep_command_nets(dut)},
        )
        self.fuse_probe.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_secure_tm_real_sense_window_test_seq(self).run()
