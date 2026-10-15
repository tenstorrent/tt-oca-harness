# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_gpio_access_filter_test - GPIO bank AxPROT access filter on the external AXI path."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_gpio_access_filter_test_seq import smu_smc_gpio_access_filter_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_gpio_access_filter_test(smu_base_test):
    """ACCESS_FILTER reset value, write filter over AWPROT 0..7 and read filter over ARPROT 0..7."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_gpio_access_filter_test SEP=1 J2A+s_axi")
        seq = smu_smc_gpio_access_filter_test_seq(self)
        await seq.run()
        assert seq.done, "gpio access filter scenario incomplete"
