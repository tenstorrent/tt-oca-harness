# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: full GPIO_CTRL entry sweep (TC_SMC_P1CG_07).

RTL exposes 68 ``GPIO_CTRL_N`` entries at 0xC000_4440 stride 0x20.
U5: OSS TB terminates ``axil_req_gpio_ctrl_o`` with
``tb_smc_gpio_ctrl_rw_stub`` (OKAY sparse storage). This sequence writes a
unique pattern per entry and reads it back — proves decode/route **and**
address-discriminating storage (not real padring pinmux function).
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
            data = 0xA500_0000 | idx
            await self.csr_write_readback(f"GPIO_CTRL_{idx}", addr, data)
        assert self.accesses == _GPIO_CTRL_COUNT * 2, (
            f"GPIO_CTRL full sweep count mismatch: {self.accesses}"
        )
