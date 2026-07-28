# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 2: GPIO_REFCLK_CTRL WR->RD (U5 RW stub).

``GPIO_REFCLK_CTRL`` @ 0xC000_4CC0 shares the adopter-padring GPIO control
plane with GPIO_CTRL_* (``axil_req_gpio_ctrl_o``). U5 stub provides OKAY
sparse storage — proves decode/route + readback, not REFCLK analog function.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_GPIO_REFCLK_CTRL_BASE = 0xC000_4CC0


class smc_gpio_refclk_ctrl_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for name, off in (("GPIO_REFCLK_CTRL_0", 0x0), ("GPIO_REFCLK_CTRL_4", 0x4)):
            data = 0xBEEF_0000 | off
            await self.csr_write_readback(name, _GPIO_REFCLK_CTRL_BASE + off, data)
        assert self.accesses == 4, (
            f"GPIO_REFCLK_CTRL sweep count mismatch: {self.accesses}"
        )
