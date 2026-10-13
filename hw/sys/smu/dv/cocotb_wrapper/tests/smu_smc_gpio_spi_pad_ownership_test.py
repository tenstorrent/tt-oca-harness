# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_gpio_spi_pad_ownership_test - GPIO pads owned by the SEP SPI host and lsio_disable."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_gpio_spi_pad_ownership_test_seq import smu_smc_gpio_spi_pad_ownership_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_gpio_spi_pad_ownership_test(smu_base_test):
    """Pads 0-3, 8 and 9 follow the SPI host until lsio_disable; pads 4-7, 10 and 54 are not driven."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_gpio_spi_pad_ownership_test "
            "SMU_WRAPPER_DEBUG_PATHS_023 SEP=1 J2A+s_axi"
        )
        seq = smu_smc_gpio_spi_pad_ownership_test_seq(self)
        await seq.run()
        assert seq.done, "gpio spi pad ownership scenario incomplete"
