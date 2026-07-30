# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: SMC_AXIL_EXTENSION Cadence I3C (TC_SMC_P1CG_19).

AXIL-extension bus at 0xC040_0000 with 6 wrap instances. Under
``smc_wrapper``, ``u_axil_extension_err_slv`` returns DECERR + 0 for every
access — this test proves decode/route into that boundary.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CDNS_I3C_AXIL_WRAPS = 6
CDNS_I3C_AXIL_BASE = 0xC040_0000
CDNS_I3C_AXIL_WRAP_STRIDE = 0x400
CDNS_I3C_AXIL_CTRL_OFFSET = 0x300

CDNS_I3C_AXIL_READS = []
for _wrap in range(CDNS_I3C_AXIL_WRAPS):
    _base = CDNS_I3C_AXIL_BASE + _wrap * CDNS_I3C_AXIL_WRAP_STRIDE
    CDNS_I3C_AXIL_READS.append((f"AXIL_EXT_I3C_WRAP_{_wrap}_BASE", _base, None))
    CDNS_I3C_AXIL_READS.append(
        (f"AXIL_EXT_I3C_WRAP_{_wrap}_CTRL", _base + CDNS_I3C_AXIL_CTRL_OFFSET, None)
    )


class smc_cdns_i3c_axil_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        await self.csr_read_many_decerr_zero(CDNS_I3C_AXIL_READS)
        assert self.accesses == len(CDNS_I3C_AXIL_READS), (
            "Cadence I3C AXIL extension precheck count mismatch"
        )
