# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_fuse_sense_sequence_test - SMC fuse-sense completion ordering.

Measured against the `smc_fuse_sense_done_o` ("SMC fuse sense completion
output") and `smc_fuse_reset_n_delayed_o` ("Delayed fuse reset output") rows of
`hw/sys/smu/doc/port_table.adoc`, the only SMU specification in this tree; it
names the two ports but not their relative order, so the ordering leg below is
a check on the elaborated design with no document behind it. On the `--dut smu`
production wrapper built with
compile_smu_chiplet and run under the sep_rtl_fuse_sense run mode, which
leaves +skip_fuse_sense unset so the SMC eFuse bank model answers the sense:
smc_fuse_sense_done_o rises once, after the SMC primary reset released and after
eFuse read traffic appeared on the SMU eFuse shim command port, and
smc_fuse_reset_n_delayed_o releases after that rise rather than with the cold
reset.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_fuse_sense_sequence_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_fuse_sense_probe import SmuFuseSenseProbe, smc_command_nets
from seq_lib.smu_smc_fuse_sense_sequence_seq import smu_smc_fuse_sense_sequence_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_fuse_sense_sequence_test(smu_base_test):
    """SMC fuse sense completes and the delayed fuse reset follows it."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Arm the fuse-sense observers, then run the shared bring-up.

        The sense starts when the SMC primary reset releases, which happens
        inside the bring-up sequence, so the observers cannot wait for
        run_scenario.
        """
        dut = cocotb.top
        self.fuse_probe = SmuFuseSenseProbe(
            self,
            edge_signals={
                "rst_cold_n_o": dut.rst_cold_n_o,
                "rst_primary_smc_clk_n_o": dut.rst_primary_smc_clk_n_o,
                "smc_fuse_sense_done_o": dut.smc_fuse_sense_done_o,
                "smc_fuse_reset_n_delayed_o": dut.smc_fuse_reset_n_delayed_o,
            },
            command_nets={"smc_efuse_shim": smc_command_nets(dut)},
        )
        self.fuse_probe.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_smc_fuse_sense_sequence_seq(self).run()
