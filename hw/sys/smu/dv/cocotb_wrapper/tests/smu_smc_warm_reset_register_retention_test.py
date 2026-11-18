# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_warm_reset_register_retention_test - registers across the CORE0 watchdog warm reset.

Runs the real SMC fuse sense (no +skip_fuse_sense): the eFuse shim command
observer and the smc_fuse_sense_done_o edge observer are armed before bring-up,
so the one cold-boot sense is on record before the warm reset that must not
repeat it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_warm_reset_register_retention_test --target compile_smu_chiplet
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_fuse_sense_probe import SmuFuseSenseProbe, smc_command_nets
from seq_lib.smu_smc_warm_reset_register_retention_test_seq import (
    smu_smc_warm_reset_register_retention_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_warm_reset_register_retention_test(smu_base_test):
    """Reset-unit, isolation registers and the fuse sense survive the warm reset; CORE0 returns."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-WARM-RET-EVENT",
        "CHK-WARM-RET-ISO",
        "CHK-WARM-RET-NO-RESENSE",
        "CHK-WARM-RET-PRIMARY-STAY",
        "CHK-WARM-RET-SSCFG",
        "CHK-WARM-RET-SSCOLD",
        "CHK-WARM-RET-SSWARM",
        "CHK-WARM-RET-WDT-RETURN",
    )

    async def bring_up(self) -> None:
        """Arm the sense observers, then run the shared bring-up."""
        dut = cocotb.top
        self.fuse_probe = SmuFuseSenseProbe(
            self,
            edge_signals={"smc_fuse_sense_done_o": dut.smc_fuse_sense_done_o},
            command_nets={"smc_efuse_shim": smc_command_nets(dut)},
        )
        self.fuse_probe.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_warm_reset_register_retention_test SEP=1 JTAG")
        seq = smu_smc_warm_reset_register_retention_test_seq(self)
        await seq.run()
        assert seq.done, "warm reset register retention scenario incomplete"
