# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_wdt_sanity_test — CORE0 WDT unlock + CMP via J2A."""

from __future__ import annotations

import pyuvm

from seq_lib.smc_wdt_sanity_test_seq import smc_wdt_sanity_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_wdt_sanity_test(smu_base_test):
    """CORE0 WDT magic unlock and CMP program evidence."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smc_wdt_sanity_test TierA WDT unlock SEP=0 J2A"
        )
        seq = smc_wdt_sanity_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"wdt_sanity incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
