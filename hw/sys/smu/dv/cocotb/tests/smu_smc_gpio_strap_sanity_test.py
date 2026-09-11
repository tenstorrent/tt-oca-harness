# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_gpio_strap_sanity_test — STRAPS_* track captured_straps_i."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_gpio_strap_sanity_test_seq import smu_smc_gpio_strap_sanity_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_gpio_strap_sanity_test(smu_base_test):
    """Reset-unit STRAPS_* track captured_straps_i (GPIO pad strap path)."""

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=BARE smu_smc_gpio_strap_sanity_test TierA straps SEP=0 J2A")
        seq = smu_smc_gpio_strap_sanity_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"gpio_strap incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
