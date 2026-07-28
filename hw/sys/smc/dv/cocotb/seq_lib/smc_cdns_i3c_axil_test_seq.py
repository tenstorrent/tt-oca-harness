# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: SMC_AXIL_EXTENSION Cadence I3C (TC_SMC_P1CG_19).

RTL exposes a separate Cadence I3C via the AXIL-extension bus at
0xC040_0000, with **6** wrap instances (wrap N base = 0xC040_0000 +
N*0x400) each carrying an I3C_CTRL block at + 0x300 offset. This test
reads a representative CSR at each wrap base + CTRL to prove decode.
Bounded reads — the AXIL extension may be clock-gated in the current
OSS bring-up.

Round 4 (2026-07-02): extended from 4 -> 6 wraps to match the RTL
(wrap_4 @ 0xC040_1000, wrap_5 @ 0xC040_1400 were previously unreached).
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


# The AXIL-extension bus (0xC040_0000) is an externalised macro port
# terminated by the OSS bench DECERR boundary responder, so every read returns
# DECERR + the 0xBADCAB1E signature on both Verilator and VCS. See tb_top.sv
# u_extension_macro_model (prim_axi_lite_err_slv).


class smc_cdns_i3c_axil_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # csr_read_many_err_signature asserts, per window, the error response
        # AND the exact 0xBADCAB1E signature (no timeout tolerated) -- stricter
        # than the previous bounded read + value-only check.
        await self.csr_read_many_err_signature(CDNS_I3C_AXIL_READS)
        assert self.accesses == len(CDNS_I3C_AXIL_READS), (
            "Cadence I3C AXIL extension precheck count mismatch"
        )
