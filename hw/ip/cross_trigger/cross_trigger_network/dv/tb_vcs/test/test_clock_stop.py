# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Cross Trigger Network Clock Stop Test

Test clock stop request OR aggregation.
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from test.test_base import *


@cocotb.test()
async def test_clock_stop(dut):
    """Test clock stop control logic"""

    # Start clocks
    clock = await start_clocks(dut, period_ns=10)

    # Initialize DUT
    await init(dut)

    # Initialize AXI-Lite
    await init_axil(dut)

    # Wait for DUT to be ready
    await wait_cycles(dut, 10)

    dut._log.info("=== CTN Clock Stop Test Starting ===")

    # Test 1: Verify stop_clks is 0 at reset
    dut._log.info("Test 1: Verify stop_clks is 0 at reset...")
    stop_clks = int(dut.stop_clks.value)
    assert stop_clks == 0, f"stop_clks should be 0 at reset, got {stop_clks}"
    dut._log.info("PASS: stop_clks = 0 at reset")

    # Test 2: Assert a single clock stop request
    dut._log.info("Test 2: single clk_stop_req assertion...")
    dut.clk_stop_req.value = 0x1
    await wait_cycles(dut, 2)

    stop_clks = int(dut.stop_clks.value)
    cla_clock_stop = int(dut.cla_clock_stop.value)
    assert stop_clks == 1, f"stop_clks should assert for a clock stop request, got {stop_clks}"
    assert cla_clock_stop == 1, f"cla_clock_stop should reflect the request OR tree, got {cla_clock_stop}"
    dut._log.info("PASS: single request asserts stop_clks and cla_clock_stop")

    # Test 3: Clear request and verify deassertion
    dut._log.info("Test 3: clear clock stop request...")
    dut.clk_stop_req.value = 0x0
    await wait_cycles(dut, 2)

    stop_clks = int(dut.stop_clks.value)
    cla_clock_stop = int(dut.cla_clock_stop.value)
    assert stop_clks == 0, f"stop_clks should be 0 when request cleared, got {stop_clks}"
    assert cla_clock_stop == 0, f"cla_clock_stop should be 0 when request cleared, got {cla_clock_stop}"
    dut._log.info("PASS: clearing the request deasserts stop_clks and cla_clock_stop")

    # Test 4: Test multiple clock stop requests (OR aggregation)
    dut._log.info("Test 4: multiple clock stop requests...")
    dut.clk_stop_req.value = 0x3  # Both requests
    await wait_cycles(dut, 2)

    stop_clks = int(dut.stop_clks.value)
    cla_clock_stop = int(dut.cla_clock_stop.value)
    assert stop_clks == 1, f"stop_clks should be 1 for multiple requests, got {stop_clks}"
    assert cla_clock_stop == 1, f"cla_clock_stop should be 1 for multiple requests, got {cla_clock_stop}"

    # Clear one request, should still be asserted
    dut.clk_stop_req.value = 0x1
    await wait_cycles(dut, 2)

    stop_clks = int(dut.stop_clks.value)
    cla_clock_stop = int(dut.cla_clock_stop.value)
    assert stop_clks == 1, f"stop_clks should be 1 with one request remaining, got {stop_clks}"
    assert cla_clock_stop == 1, f"cla_clock_stop should remain 1 with one request remaining, got {cla_clock_stop}"
    dut._log.info("PASS: OR aggregation works correctly")

    # Clear all
    dut.clk_stop_req.value = 0x0
    await wait_cycles(dut, 2)

    # Test 5: JTAG clock stop asserts functional halt without CLA requests
    dut._log.info("Test 5: JTAG clock stop without clk_stop_req...")
    dut.jtag_clock_stop.value = 1
    dut.clk_stop_req.value = 0x0
    await wait_cycles(dut, 2)
    stop_clks = int(dut.stop_clks.value)
    cla_clock_stop = int(dut.cla_clock_stop.value)
    assert stop_clks == 1, f"stop_clks should assert for JTAG clock stop, got {stop_clks}"
    assert cla_clock_stop == 0, f"cla_clock_stop should stay CLA-only (0), got {cla_clock_stop}"
    dut.jtag_clock_stop.value = 0
    await wait_cycles(dut, 2)
    stop_clks = int(dut.stop_clks.value)
    assert stop_clks == 0, f"stop_clks should clear when JTAG stop clears, got {stop_clks}"
    dut._log.info("PASS: JTAG clock stop folds into stop_clks_o")

    dut._log.info("=== CTN Clock Stop Test PASSED ===")
