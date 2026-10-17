# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_smc_dm_dmi_test — SMC debug module reset release, capabilities and system bus."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_smc_dm_dmi_test_seq import smu_dtp_smc_dm_dmi_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_smc_dm_dmi_test(smu_base_test):
    """SMC debug module through the SMC STAP: release, dmstatus, sbcs and a system-bus access."""

    use_shared_env = True
    required_evidence = (
        "CHK-DBG-SMC-DM-DMACTIVE",
        "CHK-DBG-SMC-DM-DMSTATUS",
        "CHK-DBG-SMC-DM-RELEASE",
        "CHK-DBG-SMC-DM-RESET-HELD",
        "CHK-DBG-SMC-DM-SBA-PATH",
        "CHK-DBG-SMC-DM-SBA-READ",
        "CHK-DBG-SMC-DM-SBA-WRITE",
        "CHK-DBG-SMC-DM-SBCS",
        "CHK-DBG-SMC-DM-SETUP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_smc_dm_dmi_test SEP=1 JTAG")
        await smu_dtp_smc_dm_dmi_test_seq(self).run()
