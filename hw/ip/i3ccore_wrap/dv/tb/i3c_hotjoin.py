# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Hot-Join  (Test Plan #35)

Skeleton for the Hot-Join flow: a target requests to join the bus and the
controller observes an IBI with status_type = HotJoin.
Compile-only: target hot-join support is design-dependent (see GAP Q-005);
this scaffolds the sequence and decodes the IBI status type.
"""

import cocotb
from cocotb.triggers import ClockCycles
from i3c_test_base import init_controller, init_target, make_env


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_hotjoin(dut):
    tb, helper, ctrl, tgt = await make_env(dut)

    # Controller up and listening for IBIs / hot-join before address assignment
    await init_controller(ctrl)
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

    # Target comes up (static addr) and would request hot-join
    await init_target(tgt, static_addr=0x10)
    await tgt.enable_ibi_mode()

    await ClockCycles(dut.clk, 200)
    status = await helper.read(0x0A0)
    tb.log.info(f"PIO_INTR_STATUS (hot-join window) = 0x{status:08X}")

    tb.log.info("Hot-join scaffold complete")
