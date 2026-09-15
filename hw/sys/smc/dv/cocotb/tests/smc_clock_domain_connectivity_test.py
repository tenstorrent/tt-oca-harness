# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The UART 16550 runs on the peripheral clock.

Closes the UART cell of SMC-CLK-PERIPH.S1 (clk_rst.adoc: The Peripheral Clock
Domain): UART0 transmits an all-zero frame and the TX low pulse, timestamped
at simulation-time resolution, must equal nine bit times of
16 x (DIVISOR + 1) clk_periph_i periods within two peripheral clocks; the
same frame on the SMC clock would fall outside that window on every seed.
The AVSBus/I2C/I3C cells, SMC-CLK-REF.S4 (behavioural PLL model) and
SMC-CLK-TELEM.S2 (rst_telemetry_ni tied in tb_top) are left open.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_clock_domain_connectivity_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_clock_domain_connectivity_test_seq import (
    EXPECTED_ACCESSES,
    smc_clock_domain_connectivity_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clock_domain_connectivity_test(smc_base_test):
    """UART0 bit time measured against the peripheral clock period."""

    required_evidence = (
        "CHK-CLOCK-DOMAIN-CONNECTIVITY",
        "CHK-CLOCK-DOMAIN-NOT-CLOSED",
        "CHK-UART-ON-CLK-PERIPH",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clock_domain_connectivity_test_seq("clock_domain_connectivity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.low_ps is not None, "the sequence ended without timing the UART frame"
        cocotb.log.info(
            "CHK-CLOCK-DOMAIN-CONNECTIVITY: UART0 low pulse %d ps vs %d ps expected (+/- %d)",
            seq.low_ps,
            seq.expected_ps,
            seq.tolerance_ps,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_ACCESSES,
            proxy=False,
            details=(
                f"UART0 all-zero frame low for {seq.low_ps} ps against {seq.expected_ps} ps of "
                f"clk_periph_i bit times"
            ),
        )
