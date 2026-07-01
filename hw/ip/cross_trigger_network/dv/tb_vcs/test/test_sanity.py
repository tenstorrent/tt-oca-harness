# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Cross Trigger Network Sanity Test

Basic sanity test to verify core functionality has not broken.
Tests AXI-Lite crossbar routing to CTPs and CTM.
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from test.test_base import (
    start_clocks, init, init_axil, axil_write, axil_read, wait_cycles,
    get_ctp_addr, get_ctm_src_config_addr,
    CTP_REG_CONFIG,
    AxiLiteMaster
)


@cocotb.test()
async def test_sanity(dut):
    """Basic sanity test for Cross Trigger Network"""

    # Start clocks
    clock = await start_clocks(dut, period_ns=10)

    # Initialize DUT
    await init(dut)

    # Initialize AXI-Lite
    await init_axil(dut)
    axil = AxiLiteMaster(dut)

    # Initialize AXI-Lite bus
    await axil.initialize_bus()

    # Wait a few cycles for DUT to be ready
    await wait_cycles(dut, 10)

    dut._log.info("=== CTN Sanity Test Starting ===")

    # Test 1: Read CTM register first (CTM is at address 0x0000)
    dut._log.info("Test 1: Reading CTM CT_SRC0_CONFIG register...")
    ctm_addr = get_ctm_src_config_addr(0)
    ctm_val = await axil_read(dut, axil, ctm_addr)
    dut._log.info(f"CTM CT_SRC0_CONFIG @ 0x{ctm_addr:08X} = 0x{ctm_val:08X}")

    # Test 2: Write and readback CTM register
    dut._log.info("Test 2: Write/readback CTM CT_SRC0_CONFIG...")
    test_ctm_val = 0x3  # Route CTP[0] and CTP[1] to CT_SRC0
    await axil_write(dut, axil, ctm_addr, test_ctm_val)
    await wait_cycles(dut, 2)
    readback = await axil_read(dut, axil, ctm_addr)
    dut._log.info(f"CTM Written: 0x{test_ctm_val:08X}, Read: 0x{readback:08X}")
    assert readback == test_ctm_val, f"CTM readback mismatch: {readback} != {test_ctm_val}"

    # Test 3: Read CTP[0] CONFIG register (CTPs start at 0x0200)
    dut._log.info("Test 3: Reading CTP[0] CONFIG register...")
    ctp0_config_addr = get_ctp_addr(0, CTP_REG_CONFIG)
    config_val = await axil_read(dut, axil, ctp0_config_addr)
    dut._log.info(
        f"CTP[0] CONFIG @ 0x{ctp0_config_addr:08X} = 0x{config_val:08X}")

    # Test 4: Write and readback CTP[0] CONFIG
    dut._log.info("Test 4: Write/readback CTP[0] CONFIG...")
    test_val = 0x1  # Set MODE to Point-to-Point
    await axil_write(dut, axil, ctp0_config_addr, test_val)
    await wait_cycles(dut, 2)
    readback = await axil_read(dut, axil, ctp0_config_addr)
    dut._log.info(f"Written: 0x{test_val:08X}, Read: 0x{readback:08X}")
    assert readback == test_val, f"CONFIG readback mismatch: {readback} != {test_val}"

    # Test 5: Read CTP[1] CONFIG (verify crossbar routes to different CTP)
    dut._log.info("Test 5: Reading CTP[1] CONFIG register...")
    ctp1_config_addr = get_ctp_addr(1, CTP_REG_CONFIG)
    config_val = await axil_read(dut, axil, ctp1_config_addr)
    dut._log.info(
        f"CTP[1] CONFIG @ 0x{ctp1_config_addr:08X} = 0x{config_val:08X}")

    # Test 6: Verify clock stop output is inactive at reset
    dut._log.info("Test 6: Verify clock stop output...")
    stop_clks = int(dut.stop_clks.value)
    dut._log.info(f"stop_clks = {stop_clks}")
    assert stop_clks == 0, f"Clock stop should be 0 at reset, got {stop_clks}"

    dut._log.info("=== CTN Sanity Test PASSED ===")
