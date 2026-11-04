# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_cold_reset_pin_timing_test - the cold reset pin's de-glitch and clock dependence.

Drives rst_cold_ni at the wrapper with powergood_i high and observes the
stable cold reset and the SMC primary reset: a pinned 31-clk_ref pulse and a
seed-drawn pulse below the 32-sample de-glitcher are filtered, a seed-drawn
hold above it asserts both within 32 to 33 clk_ref, and with clk_ref_i held
the pin does not propagate until the clock restarts
(hw/sys/smu/doc/port_table.adoc, the rst_cold_ni row).

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_cold_reset_pin_timing_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_cold_reset_pin_timing_seq import smu_cold_reset_pin_timing_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cold_reset_pin_timing_test(smu_base_test):
    """Cold pin de-glitch of 32 clk_ref, and no propagation while clk_ref_i is held."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_cold_reset_pin_timing_test SEP=1 pins")
        await smu_cold_reset_pin_timing_seq(self).run()
