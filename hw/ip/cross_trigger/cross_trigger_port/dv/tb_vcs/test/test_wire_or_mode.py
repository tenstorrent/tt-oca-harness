# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Cross Trigger Port Wire-OR Mode Tests

Tests for Wire-OR mode operation including pulse stretching and signal inversion.
"""

import cocotb
from cocotb.triggers import RisingEdge

from test.test_base import *


@cocotb.test()
async def test_wire_or_pulse_stretching(dut):
    """Test pulse stretching in Wire-OR mode"""

    clock = await start_clocks(dut, period_ns=10)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)

    # Initialize AXI-Lite bus
    await axil.initialize_bus()

    # Configure Wire-OR mode
    await reg_write(dut, axil, "CONFIG", 0x0)  # MODE=0

    # Test different STRETCH_MULT values
    for stretch_val in [0, 1, 10, 100]:
        await reg_write(dut, axil, "STRETCH_MULT", stretch_val)

        # Send pulse
        dut.u_dut.ct_src_i.value = 1
        await RisingEdge(dut.clk)
        dut.u_dut.ct_src_i.value = 0
        await RisingEdge(dut.clk)

        # Wait for BUSY to assert (pulse stretcher needs a cycle to start)
        await RisingEdge(dut.clk)

        # Count cycles while BUSY is asserted
        busy_cycles = 0
        while dut.u_dut.busy_o.value == 1 and busy_cycles < 1000:
            await RisingEdge(dut.clk)
            busy_cycles += 1

        # Verify pulse width = STRETCH_MULT + 1
        expected_cycles = stretch_val + 1
        assert busy_cycles == expected_cycles, (
            f"Pulse width mismatch: {busy_cycles} != {expected_cycles} for STRETCH_MULT={stretch_val}"
        )

    dut._log.info("Wire-OR pulse stretching test passed!")


@cocotb.test()
async def test_wire_or_signal_inversion(dut):
    """Test signal inversion in Wire-OR mode"""

    clock = await start_clocks(dut, period_ns=10)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)

    # Initialize AXI-Lite bus
    await axil.initialize_bus()

    # Configure Wire-OR mode without inversion
    await reg_write(dut, axil, "CONFIG", 0x0)  # MODE=0, INVERT=0
    await reg_write(dut, axil, "STRETCH_MULT", 10)

    # Check pad output (should be low when not active)
    await RisingEdge(dut.clk)
    dout_no_invert = dut.ct_req_out_dout.value

    # Configure with inversion
    await reg_write(dut, axil, "CONFIG", 0x2)  # MODE=0, INVERT=1

    await RisingEdge(dut.clk)
    dout_with_invert = dut.ct_req_out_dout.value

    # Verify inversion changes output
    assert dout_no_invert != dout_with_invert, "Inversion should change pad output"

    dut._log.info("Wire-OR signal inversion test passed!")


@cocotb.test()
async def test_wire_or_back_to_back_pulses(dut):
    """Test back-to-back pulses restart counter"""

    clock = await start_clocks(dut, period_ns=10)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)

    # Initialize AXI-Lite bus
    await axil.initialize_bus()

    # Configure Wire-OR mode
    await reg_write(dut, axil, "CONFIG", 0x0)
    await reg_write(dut, axil, "STRETCH_MULT", 10)

    # Send first pulse
    dut.u_dut.ct_src_i.value = 1
    await RisingEdge(dut.clk)
    dut.u_dut.ct_src_i.value = 0

    # Wait a few cycles
    for _ in range(5):
        await RisingEdge(dut.clk)

    # Send second pulse (should restart counter)
    dut.u_dut.ct_src_i.value = 1
    await RisingEdge(dut.clk)
    dut.u_dut.ct_src_i.value = 0
    await RisingEdge(dut.clk)

    # Wait for BUSY to assert
    await RisingEdge(dut.clk)

    # Count cycles from second pulse
    busy_cycles = 0
    while dut.u_dut.busy_o.value == 1 and busy_cycles < 1000:
        await RisingEdge(dut.clk)
        busy_cycles += 1

    # Should be full STRETCH_MULT + 1 cycles (10 + 1 = 11)
    assert busy_cycles == 11, f"Back-to-back pulse should restart counter: {busy_cycles} != 11"

    dut._log.info("Wire-OR back-to-back pulses test passed!")
