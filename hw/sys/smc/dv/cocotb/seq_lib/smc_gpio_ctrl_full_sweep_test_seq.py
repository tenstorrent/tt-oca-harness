# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: GPIO_CTRL window routing sweep (TC_SMC_P1CG_07).

RTL exposes 68 ``GPIO_CTRL_N`` entries at 0xC000_4440 stride 0x20.
OSS TB / ``smc_ip_integration`` terminate ``axil_req_gpio_ctrl_o`` with a
DECERR slave (not a RW stub). This sequence proves decode/route into that
boundary by reading the DECERR signature at every entry.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_GPIO_CTRL_BASE = 0xC000_4440
_GPIO_CTRL_STRIDE = 0x20
_GPIO_CTRL_COUNT = 68


class smc_gpio_ctrl_full_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for idx in range(_GPIO_CTRL_COUNT):
            addr = _GPIO_CTRL_BASE + idx * _GPIO_CTRL_STRIDE
            await self.csr_read_err_signature(f"GPIO_CTRL_{idx}", addr)
        assert self.accesses == _GPIO_CTRL_COUNT, (
            f"GPIO_CTRL full sweep count mismatch: {self.accesses}"
        )
