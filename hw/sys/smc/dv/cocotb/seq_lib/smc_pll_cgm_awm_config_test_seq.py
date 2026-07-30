# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: PLL CGM_0/1 + AWM_0/1 CSR precheck (TC_SMC_P1CG_06).

Existing PLL tests only touch PLL_CNTL at 0xC000_3000. RTL exposes
CGM 0/1 + AWM 0/1 at 0xC000_3100/3200 and 0xC000_3400/3A00. Under
``smc_wrapper``, ``pll_wrap`` completes every access with OKAY + 0.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

PLL_CGM_AWM_READS = [
    ("PLL_CGM_0",   0xC000_3100, 0),
    ("PLL_CGM_1",   0xC000_3200, 0),
    ("PLL_AWM_0",   0xC000_3400, 0),
    ("PLL_AWM_1",   0xC000_3A00, 0),
]


class smc_pll_cgm_awm_config_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        await self.csr_read_many(PLL_CGM_AWM_READS)
