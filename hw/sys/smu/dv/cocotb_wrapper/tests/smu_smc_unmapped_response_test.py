# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_unmapped_response_test — SMC responses for unmapped inbound offsets."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_unmapped_response_test_seq import smu_smc_unmapped_response_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_unmapped_response_test(smu_base_test):
    """Gap, past-extent and M-mode/Xvisor window accesses from ext_in answer DECERR or SLVERR."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_unmapped_response_test SMU_FABRIC_XBAR_017 SEP=1 J2A+s_axi"
        )
        seq = smu_smc_unmapped_response_test_seq(self)
        await seq.run()
        assert seq.done, "unmapped response scenario incomplete"
