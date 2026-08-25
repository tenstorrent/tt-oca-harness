# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap-0 register vs LSIO mux."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_p0_mux_test_seq import smc_gpio_p0_mux_test_seq


@pyuvm.test()
class smc_gpio_p0_mux_test(smc_base_test):
    """GPIO0 interface_enable vs lsio_select mux."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_p0_mux_test_seq("gpio_p0_mux_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.reg_ok and seq.priority_ok and seq.lsio_ok, (
            f"gpio p0 mux incomplete reg={seq.reg_ok} "
            f"prio={seq.priority_ok} lsio={seq.lsio_ok}"
        )
