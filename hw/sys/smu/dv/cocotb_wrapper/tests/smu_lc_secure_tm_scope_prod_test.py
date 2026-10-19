# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_secure_tm_scope_prod_test - in PROD the secure test-mode strap opens no debug path.

Spec: hw/sys/sep/doc/test_mode.adoc, hw/sys/sep/doc/security_disable.adoc,
hw/sys/sep/doc/lifecycle_controller.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_secure_tm_scope_prod_test --target compile_smu_chiplet
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_lc_secure_tm_scope_prod_test_seq import (
    SecureTmResetProbe,
    smu_lc_secure_tm_scope_prod_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_secure_tm_scope_prod_test(smu_base_test):
    """SECURE_TM leaves feature control and the DFT SIBs alone, with and without a SEC_DIS match."""

    use_shared_env = True

    def drive_idle_inputs(self) -> None:
        super().drive_idle_inputs()
        cocotb.top.tb_secure_tm_req.value = 1

    async def bring_up(self) -> None:
        self.reset_probe = SecureTmResetProbe(cocotb.top)
        self.reset_probe_task = cocotb.start_soon(self.reset_probe.run())
        await super().bring_up()

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_secure_tm_scope_prod_test SEP=1 PROD strap high with and "
            "without a SEC_DIS match"
        )
        await smu_lc_secure_tm_scope_prod_test_seq(self).run()
