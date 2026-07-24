# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: PLL CGM_0/1 + AWM_0/1 CSR precheck (TC_SMC_P1CG_06).

Existing PLL tests only touch PLL_CNTL at 0xC000_3000. RTL exposes
CGM 0/1 clock generation blocks + AWM 0/1 adaptive-width modulation
blocks at 0xC000_3100/3200 and 0xC000_3400/3A00.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

PLL_CGM_AWM_READS = [
    ("PLL_CGM_0",   0xC000_3100, None),
    ("PLL_CGM_1",   0xC000_3200, None),
    ("PLL_AWM_0",   0xC000_3400, None),
    ("PLL_AWM_1",   0xC000_3A00, None),
]


# The whole PLL_WRAP window (0xC0003000..0xC0003EE2) is an externalised macro
# port terminated by the OSS bench DECERR boundary responder, so every read
# returns this signature. See tb_top.sv u_pll_macro_model (prim_axi_lite_err_slv).
_PLL_DECERR_SIGNATURE = 0xBADCAB1E


class smc_pll_cgm_awm_config_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # The whole PLL_WRAP window is an externalised macro port terminated by
        # the OSS bench DECERR boundary responder: csr_read_err_signature asserts
        # BOTH the error response AND the 0xBADCAB1E signature per read.
        for name, addr, _expected in PLL_CGM_AWM_READS:
            await self.csr_read_err_signature(name, addr)
