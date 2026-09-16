# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_peripheral_irq_test - the raw GPIO and UART interrupt vectors.

port_table.adoc brings gpio_interrupt_o and uart_interrupt_o out of the
wrapper as raw per-instance interrupt vectors, and nothing had raised either.
This leaf arms GPIO pin 0 through its SMC register -- taking the pin away from
its LSIO owner so the pad input buffer opens -- drives the pad and requires
the interrupt and the DATA_CTRL.PAD2CORE mirror to follow it both ways, then
enables the UART transmitter-empty source and requires the pin and IIR to
agree on it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_peripheral_irq_test --target compile_smu_chiplet_sep_rtl
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_peripheral_irq_seq import smu_smc_peripheral_irq_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_peripheral_irq_test(smu_base_test):
    """GPIO and UART raw interrupt outputs at the SMU boundary."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_peripheral_irq_seq(self).run()
