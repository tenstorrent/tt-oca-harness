# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_fuse_sense_done_test - SEP fuse-sense completion at the boundary.

Measured against the `sep_fuse_sense_done_o` row of
`hw/sys/smu/doc/port_table.adoc` ("SEP fuse sense done output"); the ordering
the checks require is a property of the elaborated design, not of that row. On
the `--dut smu` production
wrapper built with compile_smu_chiplet and run under the
sep_rtl_fuse_sense run mode, which leaves +skip_fuse_sense and the SEP shadow
preload unset so the SEP eFuse bank model answers the sense:
sep_fuse_sense_skipped_o reads 0, sep_fuse_sense_done_o is low under cold
reset, and it rises once after the cold reset released and after SEP eFuse read
traffic appeared on the SMU eFuse shim command port.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_fuse_sense_done_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_fuse_sense_probe import SmuFuseSenseProbe, sep_command_nets
from seq_lib.smu_sep_fuse_sense_done_seq import smu_sep_fuse_sense_done_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_fuse_sense_done_test(smu_base_test):
    """SEP fuse sense completes and reports on sep_fuse_sense_done_o."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Arm the fuse-sense observers, then run the shared bring-up.

        The sense starts when the SEP leaves reset, which happens inside the
        bring-up sequence, so the observers cannot wait for run_scenario.
        """
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
        await smu_sep_fuse_sense_done_seq(self).run()
