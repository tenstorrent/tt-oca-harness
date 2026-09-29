# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_telemetry_atb_capture_test - the ATB telemetry source at the SMU boundary.

Drives one complete last-flagged ATB message into telemetry receiver 0 through
the wrapper's telemetry pins and reads it back out of the receiver's registers
over JTAG2AXI: the buffer goes non-empty, the probe id matches the one framed
on the beats, one valid bit appears for the one counter's worth of valid blocks
sent, and counter 0 reads back the byte that filled them. The frame is a
DV-owned table transcribed from the telemetry receiver specification
(hw/ip/telemetry_receiver/doc, regs); the sequence names the positions that
specification leaves open. A second leg drives the ATB flush handshake, where
the request holds until telemetry_afready_i acknowledges it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_telemetry_atb_capture_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_telemetry_atb_capture_seq import smu_telemetry_atb_capture_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_telemetry_atb_capture_test(smu_base_test):
    """An ATB message and a flush handshake at the wrapper telemetry pins."""

    use_shared_env = True

    #: clk_telemetry_i (clk_ref_i) runs faster than the receiver's clk_smu_i so
    #: back-to-back ATB beats fill the crossing FIFO (S7).
    TELEMETRY_CLK_PERIOD_NS = 10
    RECEIVER_CLK_PERIOD_NS = 12

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.ref_clk_period_ns = self.TELEMETRY_CLK_PERIOD_NS
        self.cfg.smu_clk_period_ns = self.RECEIVER_CLK_PERIOD_NS

    async def run_scenario(self) -> None:
        await smu_telemetry_atb_capture_seq(self).run()
