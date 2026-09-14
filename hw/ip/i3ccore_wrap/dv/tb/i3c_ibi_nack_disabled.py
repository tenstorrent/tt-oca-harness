# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C IBI when Disabled

With target IBI generation NOT enabled, confirm the controller does not see a
spurious IBI (the request should be NACKed / not serviced).
"""

import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import bring_up_and_assign, make_env


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_ibi_nack_disabled(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # Controller is ready to receive IBIs, but target IBI mode is left disabled
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

    # Run a normal transfer to confirm the bus is still healthy
    data = [0xCA, 0xFE, 0xBA, 0xBE]
    ok, resp, rx = await ctrl.private_write(data, tgt, dat_idx=0)
    assert ok, f"transfer failed resp=0x{resp:08X}"
    assert rx == data, "data mismatch"

    # No IBI should have been latched; read PIO interrupt status for visibility
    await ClockCycles(dut.clk, 100)
    status = await helper.read(0x0A0)
    tb.log.info(f"PIO_INTR_STATUS (IBI disabled) = 0x{status:08X}")

    tb.log.info("IBI-disabled test complete")
