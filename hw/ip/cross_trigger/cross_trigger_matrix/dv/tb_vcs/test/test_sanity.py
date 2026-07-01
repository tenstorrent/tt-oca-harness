# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Sanity test for Cross Trigger Matrix IP
Basic smoke test to verify core functionality
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from test.test_base import (
    start_clocks, init, init_axil,
    AxiLiteMaster, write_ct_src_config, read_ct_src_config,
    pulse_ct_dst, wait_for_ct_src_pulse, check_ct_src_low
)

@cocotb.test()
async def test_sanity(dut):
    """Basic sanity test: route CT_Dst[0] to CT_Src[0]"""

    # Start clock
    await start_clocks(dut)

    # Initialize
    await init(dut)
    await init_axil(dut)

    # Create AXI-Lite master and initialize bus
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    # Configure CT_Src[0] to select CT_Dst[0]
    dut._log.info("Writing CT_SRC0_CONFIG = 0x00000001")
    await write_ct_src_config(dut, axil, 0, 0x00000001)
    dut._log.info("Write complete")

    # Verify register readback
    dut._log.info("Reading CT_SRC0_CONFIG")
    readback = await read_ct_src_config(dut, axil, 0)
    dut._log.info(f"Readback value: 0x{readback:08x}")
    assert readback == 0x00000001, f"Register readback mismatch: expected 0x00000001, got 0x{readback:08x}"

    # Wait a few cycles for configuration to settle
    for _ in range(5):
        await RisingEdge(dut.clk)

    # Verify CT_Src[0] is low initially
    assert (dut.ct_src.value & 0x1) == 0, "CT_Src[0] should be low initially"

    # Send pulse on CT_Dst[0]
    await pulse_ct_dst(dut, 0, duration_cycles=1)

    # Wait for pulse to propagate (1 cycle registered delay)
    await RisingEdge(dut.clk)

    # Verify pulse appears on CT_Src[0]
    assert (dut.ct_src.value & 0x1) == 1, "CT_Src[0] should pulse after CT_Dst[0] pulse"

    # Wait one more cycle
    await RisingEdge(dut.clk)

    # Verify pulse clears (should be registered, so clears after input clears)
    assert (dut.ct_src.value & 0x1) == 0, "CT_Src[0] should clear after pulse"

    # Verify other CT_Src outputs remain low
    assert (dut.ct_src.value >> 1) == 0, "Other CT_Src outputs should remain low"

    dut._log.info("Sanity test passed!")
