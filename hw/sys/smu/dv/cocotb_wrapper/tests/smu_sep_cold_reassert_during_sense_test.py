# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_cold_reassert_during_sense_test - cold reset re-asserted around the SEP fuse sense.

Contract SMU_SEP_005, anchor smu_sep_cold_reassert_during_sense_test.
Spec: hw/sys/sep/doc/reset_controller.adoc, hw/sys/sep/doc/clk_rst.adoc,
hw/sys/sep/doc/otp_fuse_controller.adoc, hw/ip/efuse/doc/architecture.adoc.

Runs under sep_rtl_fuse_sense: the SEP eFuse bank model answers a real sense. rst_cold_ni is
asserted after done and after response words 0, 128 and near 255, and a full sense runs after
the last release.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_cold_reassert_during_sense_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_fuse_sense_probe import SmuFuseSenseProbe, sep_command_nets
from seq_lib.smu_sep_cold_reassert_during_sense_test_seq import (
    smu_sep_cold_reassert_during_sense_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_cold_reassert_during_sense_test(smu_base_test):
    """Cold reset re-assertion clears done, resets the SEP and restarts the sense."""

    use_shared_env = True

    async def bring_up(self) -> None:
        dut = cocotb.top
        self.fuse_probe = SmuFuseSenseProbe(
            self,
            edge_signals={
                "rst_cold_n_o": dut.rst_cold_n_o,
                "sep_reset_n_o": dut.sep_reset_n_o,
                "sep_fuse_sense_done_o": dut.sep_fuse_sense_done_o,
            },
            command_nets={"sep_efuse_shim": sep_command_nets(dut)},
        )
        self.fuse_probe.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_sep_cold_reassert_during_sense_test_seq(self).run()
