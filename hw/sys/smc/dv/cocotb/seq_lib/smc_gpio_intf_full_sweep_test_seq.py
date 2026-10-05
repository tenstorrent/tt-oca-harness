# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Full GPIO_INTF sweep.

Sweeps every PeakRDL GPIO_INTF DATA_CTRL entry to prove decode is alive.
Reset content is 0 unless ``lsio_enable`` HW input is tied high (bit25).
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import GPIO_INTF_NUM, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_GPIO_INTF_COUNT = GPIO_INTF_NUM
_GPIO_INTF_DEFAULT_BIT25 = 0x0200_0000


class smc_gpio_intf_full_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        lsio_enabled = 0
        for idx in range(_GPIO_INTF_COUNT):
            addr = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", idx)
            got = await self.csr_read(f"GPIO_INTF_{idx}", addr)
            assert got in (0x0, _GPIO_INTF_DEFAULT_BIT25), (
                f"GPIO_INTF_{idx} @ 0x{addr:08x}: unexpected DATA_CTRL "
                f"0x{got:08x} (want 0 or lsio_enable=1)"
            )
            lsio_enabled += got == _GPIO_INTF_DEFAULT_BIT25
        self.assert_all_reachable(_GPIO_INTF_COUNT, "GPIO_INTF_FULL_SWEEP")
        cocotb.log.info(
            "CHK-GPIO-INTF-DATA-CTRL-SWEEP: %d GPIO_INTF DATA_CTRL entries each returned "
            "OKAY and a reset word of 0x0 or 0x%08x (lsio_enable bit only); %d read 0x0 and "
            "%d read the lsio_enable word; %d SEP_IN accesses checked by the scoreboard",
            _GPIO_INTF_COUNT,
            _GPIO_INTF_DEFAULT_BIT25,
            _GPIO_INTF_COUNT - lsio_enabled,
            lsio_enabled,
            self.accesses,
        )
