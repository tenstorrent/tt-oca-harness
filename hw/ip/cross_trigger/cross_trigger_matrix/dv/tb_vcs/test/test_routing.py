# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Comprehensive routing tests for Cross Trigger Matrix IP
"""

import cocotb
from cocotb.triggers import RisingEdge

from test.test_base import (
    CT_DST_SELECT_MASK,
    NUM_CT_SRC,
    AxiLiteMaster,
    init,
    init_axil,
    pulse_ct_dst,
    read_ct_src_config,
    start_clocks,
    write_ct_src_config,
)


@cocotb.test()
async def test_single_source_routing(dut):
    """Test routing each CT_Dst to each CT_Src"""

    await start_clocks(dut)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Test all combinations: CT_Dst[i] -> CT_Src[j]
    for src_idx in range(4):
        # Clear all CT_Src configurations first to avoid interference
        for clear_src in range(4):
            await write_ct_src_config(dut, axil, clear_src, 0x00000000)
        await RisingEdge(dut.clk)

        for dst_idx in range(4):
            # Configure routing for this specific CT_Src
            select_mask = 1 << dst_idx
            await write_ct_src_config(dut, axil, src_idx, select_mask)

            # Wait for configuration to settle
            await RisingEdge(dut.clk)

            # Send pulse on CT_Dst[dst_idx]
            await pulse_ct_dst(dut, dst_idx, duration_cycles=1)

            # Wait for pulse to propagate (1 cycle registered delay)
            await RisingEdge(dut.clk)

            # Verify pulse appears on CT_Src[src_idx]
            assert (dut.ct_src.value >> src_idx) & 1 == 1, (
                f"CT_Src[{src_idx}] should pulse when CT_Dst[{dst_idx}] pulses"
            )

            # Verify other CT_Src outputs don't pulse
            for other_src in range(4):
                if other_src != src_idx:
                    assert (dut.ct_src.value >> other_src) & 1 == 0, (
                        f"CT_Src[{other_src}] should not pulse (only CT_Src[{src_idx}] configured)"
                    )

            # Clear and wait
            await RisingEdge(dut.clk)
            assert (dut.ct_src.value >> src_idx) & 1 == 0, (
                f"CT_Src[{src_idx}] should clear after pulse"
            )

    dut._log.info("Single source routing test passed!")


@cocotb.test()
async def test_multi_source_or(dut):
    """Test ORing multiple CT_Dst sources to one CT_Src"""

    await start_clocks(dut)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Configure CT_Src[0] to select CT_Dst[0] and CT_Dst[1]
    await write_ct_src_config(dut, axil, 0, 0x00000003)  # Bits 0 and 1 set

    await RisingEdge(dut.clk)

    # Test CT_Dst[0] alone
    await pulse_ct_dst(dut, 0, duration_cycles=1)
    await RisingEdge(dut.clk)
    assert (dut.ct_src.value & 0x1) == 1, "CT_Src[0] should pulse from CT_Dst[0]"
    await RisingEdge(dut.clk)
    assert (dut.ct_src.value & 0x1) == 0, "CT_Src[0] should clear"

    # Test CT_Dst[1] alone
    await pulse_ct_dst(dut, 1, duration_cycles=1)
    await RisingEdge(dut.clk)
    assert (dut.ct_src.value & 0x1) == 1, "CT_Src[0] should pulse from CT_Dst[1]"
    await RisingEdge(dut.clk)
    assert (dut.ct_src.value & 0x1) == 0, "CT_Src[0] should clear"

    # Test simultaneous pulses by sending pulses on both CT_Dst in quick succession
    # This effectively tests OR behavior: if either input pulses, output should pulse
    # We've already verified individual pulses work, so OR logic is correct.
    # For true simultaneous pulses, we verify by ensuring both can cause output.
    await RisingEdge(dut.clk)
    # Send pulse on CT_Dst[0], then immediately on CT_Dst[1] (before first clears)
    dut.ct_dst.value = 0x1  # CT_Dst[0]
    await RisingEdge(dut.clk)
    # Before CT_Dst[0] clears, also set CT_Dst[1] (simulating overlap)
    dut.ct_dst.value = 0x3  # Both CT_Dst[0] and CT_Dst[1]
    await RisingEdge(dut.clk)
    # Output should be high (OR of both)
    assert (dut.ct_src.value & 0x1) == 1, "CT_Src[0] should pulse when both CT_Dst are high"
    # Clear both and wait for registered output to clear
    dut.ct_dst.value = 0x0
    await RisingEdge(dut.clk)  # Register captures the cleared value
    await RisingEdge(dut.clk)  # Wait one more cycle for output to stabilize
    assert (dut.ct_src.value & 0x1) == 0, "CT_Src[0] should clear after inputs cleared"

    dut._log.info("Multi-source OR test passed!")


@cocotb.test()
async def test_broadcast(dut):
    """Test broadcasting one CT_Dst to multiple CT_Src"""

    await start_clocks(dut)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Configure CT_Src[0], CT_Src[1], CT_Src[2] to all select CT_Dst[2]
    await write_ct_src_config(dut, axil, 0, 0x00000004)  # Bit 2
    await write_ct_src_config(dut, axil, 1, 0x00000004)  # Bit 2
    await write_ct_src_config(dut, axil, 2, 0x00000004)  # Bit 2

    await RisingEdge(dut.clk)

    # Send pulse on CT_Dst[2]
    await pulse_ct_dst(dut, 2, duration_cycles=1)
    await RisingEdge(dut.clk)

    # Verify all three CT_Src outputs pulse
    assert (dut.ct_src.value & 0x7) == 0x7, "CT_Src[2:0] should all pulse"

    await RisingEdge(dut.clk)
    assert (dut.ct_src.value & 0x7) == 0x0, "CT_Src[2:0] should all clear"

    dut._log.info("Broadcast test passed!")


@cocotb.test()
async def test_disable_output(dut):
    """Test that all-zero select disables CT_Src output"""

    await start_clocks(dut)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Configure CT_Src[0] with all-zero (disabled)
    await write_ct_src_config(dut, axil, 0, 0x00000000)

    await RisingEdge(dut.clk)

    # Send pulses on all CT_Dst
    for dst_idx in range(4):
        await pulse_ct_dst(dut, dst_idx, duration_cycles=1)
        await RisingEdge(dut.clk)
        # Verify CT_Src[0] remains low
        assert (dut.ct_src.value & 0x1) == 0, (
            f"CT_Src[0] should remain low when disabled, even with CT_Dst[{dst_idx}] pulse"
        )
        await RisingEdge(dut.clk)

    dut._log.info("Disable output test passed!")


@cocotb.test()
async def test_register_readback(dut):
    """Test register readback functionality"""

    await start_clocks(dut)
    await init(dut)
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Test various values, including all-ones to check that the bits above the
    # select field read back as zero
    test_values = [0x00000001, 0x0000000F, 0x000000AA, 0xFFFFFFFF]

    for src_idx in range(NUM_CT_SRC):
        for value in test_values:
            # Write value
            await write_ct_src_config(dut, axil, src_idx, value)

            # Read back
            expected = value & CT_DST_SELECT_MASK
            readback = await read_ct_src_config(dut, axil, src_idx)
            assert readback == expected, (
                f"CT_SRC[{src_idx}] readback mismatch: wrote 0x{value:08x}, expected 0x{expected:08x}, read 0x{readback:08x}"
            )

    dut._log.info("Register readback test passed!")
