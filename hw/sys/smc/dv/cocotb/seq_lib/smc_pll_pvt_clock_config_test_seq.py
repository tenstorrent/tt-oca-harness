# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PLL-window reachability + internal clock-gate CSR precheck.

Confirms the PLL AXI-Lite window is reachable (no hang). Under
``smc_wrapper``, ``smc_ip_integration``'s ``pll_wrap`` returns OKAY + 0x0.
See ``smc_macro_axil_routing_test`` for full per-port routing/isolation.
"""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18
PLL_CGM0_STATUS = 0xC000_3000


class smc_pll_pvt_clock_config_test_seq(SmcCsrSeq):
    """Read the internal clock-gate CSR + probe PLL-window reachability."""

    def __init__(self, name: str = "smc_pll_pvt_clock_config_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_read("PLL_CGM0_STATUS", PLL_CGM0_STATUS, expected=0)
        assert self.timeouts == 0, "PLL window should respond (no timeout)"
        assert self.accesses == 2, "PLL reachability precheck mismatch"
