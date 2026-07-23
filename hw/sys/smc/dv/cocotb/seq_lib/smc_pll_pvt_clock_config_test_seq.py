# SPDX-License-Identifier: Apache-2.0
"""PLL-window reachability + internal clock-gate CSR precheck.

NOTE: the PLL/PVT windows are DECERR boundary responders in the OSS bench, so
this sequence does NOT read any PLL/PVT clock or status content. It only reads
the internal clock-gate control register (value unchecked) and confirms the PLL
window is reachable (returns the DECERR signature). See smc_macro_axil_routing_test.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
PLL_CGM0_STATUS = 0xC000_3000


class smc_pll_pvt_clock_config_test_seq(SmcCsrSeq):
    """Read the internal clock-gate CSR + probe PLL-window reachability (DECERR)."""

    def __init__(self, name: str = "smc_pll_pvt_clock_config_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # NOTE: this reads the internal clock-gate control CSR only (value is not
        # checked here); it does NOT observe any PLL/PVT clock or status content.
        await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        # The PLL macro window terminates in the OSS bench with a DECERR *boundary
        # responder* (prim_axi_lite_err_slv in tb_top), NOT a functional macro
        # model. The read reaches the PLL master port and returns the DECERR
        # signature instead of hanging, which confirms the periph AXI-Lite xbar
        # route to the PLL window is reachable. This proves reachability only, not
        # any register content; full per-port routing/isolation is covered by
        # smc_macro_axil_routing_test.
        rdata = await self.csr_read_allow_error("PLL_CGM0_STATUS", PLL_CGM0_STATUS)
        assert (rdata & 0xFFFFFFFF) == 0xBADCAB1E, (
            f"PLL window did not return the DECERR boundary-responder signature: 0x{rdata:x}"
        )
        assert self.timeouts == 0, "PLL window should now respond (no timeout)"
        assert self.accesses == 2, "PLL/PVT reachability precheck mismatch"
