# SPDX-License-Identifier: Apache-2.0
"""PLL-window reachability + internal clock-gate CSR precheck.

Confirms the PLL AXI-Lite window is reachable (no hang). On bare ``smc`` the
TB terminates the window with a DECERR boundary responder (0xBADCAB1E). On
``smc_wrapper``, ``smc_ip_integration``'s ``pll_wrap`` returns OKAY + 0x0.
Either signature proves reachability; see smc_macro_axil_routing_test for
full per-port routing/isolation.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
PLL_CGM0_STATUS = 0xC000_3000
# Bare TB DECERR err_slv signature vs smc_wrapper pll_wrap OKAY zero-data.
_PLL_REACHABLE_DATA = (0xBADCAB1E, 0x00000000)


class smc_pll_pvt_clock_config_test_seq(SmcCsrSeq):
    """Read the internal clock-gate CSR + probe PLL-window reachability."""

    def __init__(self, name: str = "smc_pll_pvt_clock_config_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # NOTE: this reads the internal clock-gate control CSR only (value is not
        # checked here); it does NOT observe any PLL/PVT clock or status content.
        await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        rdata = await self.csr_read_allow_error("PLL_CGM0_STATUS", PLL_CGM0_STATUS)
        data = rdata & 0xFFFFFFFF
        assert data in _PLL_REACHABLE_DATA, (
            "PLL window unreachable: expected DECERR signature 0xBADCAB1E "
            f"(bare) or OKAY 0x0 (smc_wrapper pll_wrap), got 0x{data:x}"
        )
        assert self.timeouts == 0, "PLL window should now respond (no timeout)"
        assert self.accesses == 2, "PLL/PVT reachability precheck mismatch"
