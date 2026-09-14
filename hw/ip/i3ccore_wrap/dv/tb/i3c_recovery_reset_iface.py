# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Recovery / Reset Interface

Observes the recovery interface outputs and drives a RSTACT peripheral reset,
acknowledging it via peripheral_reset_done. The full recovery-image flow is not
exercised.
"""

import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import bring_up_and_assign, make_env


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_recovery_reset_iface(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # Sample recovery interface outputs (tb_i3ccore top-level wires)
    tb.log.info(f"recovery_payload_available = {dut.recovery_payload_available.value}")
    tb.log.info(f"recovery_image_activated   = {dut.recovery_image_activated.value}")
    tb.log.info(f"peripheral_reset           = {dut.peripheral_reset.value}")
    tb.log.info(f"escalated_reset            = {dut.escalated_reset.value}")

    # Issue RSTACT peripheral reset (defining byte 0x02) and ack the reset
    ok = await ctrl.rstact(0x02, dat_idx=0)
    tb.log.info(f"RSTACT peripheral-reset ok={ok}")
    dut.peripheral_reset_done.value = 1 << 0
    await ClockCycles(dut.clk, 20)
    dut.peripheral_reset_done.value = 0

    tb.log.info("Recovery/reset interface test complete")
