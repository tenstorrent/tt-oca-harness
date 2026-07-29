# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: SMC_PVT_WRAP_DROOP sweep (TC_SMC_P1CG_22).

Droop-monitor sub-block at 0xC000_7400. Under ``smc_wrapper``,
``pvt_wrap`` returns OKAY + 0 for the whole PVT window.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

PVT_DROOP_READS = [
    ("DROOP_ENABLES",             0xC000_7400),
    ("DROOP_SAMPLE_STROBE",       0xC000_7404),
    ("DROOP_TARGET_MONITOR_CODE", 0xC000_7408),
    ("DROOP_CONFIG",              0xC000_740C),
    ("DROOP_MEAS_DURATION0",      0xC000_7410),
    ("DROOP_LONG_TERM_MAX_CODE",  0xC000_7418),
    ("DROOP_FORCE",               0xC000_7438),
    ("DROOP_SAMPLED_DROOP",       0xC000_7440),
    ("DROOP_CONFIG_SETTING_0_LW", 0xC000_744C),
    ("DROOP_PERCENT_DELAY_TH0",   0xC000_74EC),
]


class smc_pvt_droop_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for name, addr in PVT_DROOP_READS:
            await self.csr_read(name, addr, expected=0)
