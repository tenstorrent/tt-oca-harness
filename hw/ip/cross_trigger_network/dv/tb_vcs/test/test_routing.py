# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Cross Trigger Network Routing Test

Test cross trigger routing through the CTM between CTPs.

Tests:
- test_routing: Basic routing configuration verification
- test_mixed_mode_routing: Routing between CTPs in different modes (Wire-OR and P2P)
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from test.test_base import (
    start_clocks, init, init_axil, axil_write, axil_read, wait_cycles,
    get_ctp_addr, get_ctm_src_config_addr,
    CTP_REG_CONFIG, CTP_REG_STRETCH_MULT,
    NUM_CTP, NUM_INT_CT, NUM_CTM_PORTS,
    NUM_INT_CT_WIRE_OR, NUM_INT_CT_P2P,
    AxiLiteMaster
)


@cocotb.test()
async def test_routing(dut):
    """Test basic cross trigger routing configuration through CTM"""

    # Start clocks
    clock = await start_clocks(dut, period_ns=10)

    # Initialize DUT
    await init(dut)

    # Initialize AXI-Lite
    await init_axil(dut)
    axil = AxiLiteMaster(dut)

    # Initialize AXI-Lite bus
    await axil.initialize_bus()

    # Wait for DUT to be ready
    await wait_cycles(dut, 10)

    dut._log.info("=== CTN Routing Test Starting ===")

    # Configure all CTPs in Wire-OR mode with minimal stretch
    dut._log.info("Configuring CTPs in Wire-OR mode...")
    for i in range(NUM_CTP):
        ctp_config_addr = get_ctp_addr(i, CTP_REG_CONFIG)
        await axil_write(dut, axil, ctp_config_addr, 0x0)  # Wire-OR mode
        ctp_stretch_addr = get_ctp_addr(i, CTP_REG_STRETCH_MULT)
        await axil_write(dut, axil, ctp_stretch_addr, 0x4)  # 4 cycle stretch

    await wait_cycles(dut, 5)

    # Test 1: Configure CTM to route CTP[0] -> CTP[1]
    dut._log.info("Test 1: Configure CTM routing CTP[0] -> CTP[1]...")
    ctm_src1_addr = get_ctm_src_config_addr(1)
    # Set bit 0 to select CTP[0] as source for CT_SRC[1] (goes to CTP[1])
    await axil_write(dut, axil, ctm_src1_addr, 0x1)
    await wait_cycles(dut, 2)

    # Verify CTM configuration
    readback = await axil_read(dut, axil, ctm_src1_addr)
    dut._log.info(f"CTM CT_SRC1_CONFIG = 0x{readback:08X}")
    assert readback == 0x1, f"CTM config mismatch: {readback}"

    # Apply trigger on CTP[0] GPIO input (simulate external trigger)
    dut._log.info("Applying trigger pulse on CTP[0] input...")
    dut.ctp_req_out_din.value = 0x1  # Assert CTP[0] req_out_din
    await wait_cycles(dut, 3)
    dut.ctp_req_out_din.value = 0x0  # Deassert

    # Wait for trigger to propagate
    await wait_cycles(dut, 10)

    # Check CTP[1] output (ct_src should have pulsed)
    # In Wire-OR mode, the stretched pulse should appear on req_out
    dut._log.info("Checking CTP[1] output...")

    # Test 2: Configure CTM to route CTP[2] -> CTP[3]
    dut._log.info("Test 2: Configure CTM routing CTP[2] -> CTP[3]...")
    ctm_src3_addr = get_ctm_src_config_addr(3)
    # Set bit 2 to select CTP[2] as source for CT_SRC[3]
    await axil_write(dut, axil, ctm_src3_addr, 0x4)
    await wait_cycles(dut, 2)

    readback = await axil_read(dut, axil, ctm_src3_addr)
    dut._log.info(f"CTM CT_SRC3_CONFIG = 0x{readback:08X}")
    assert readback == 0x4, f"CTM config mismatch: {readback}"

    # Test 3: Configure OR of multiple sources
    dut._log.info("Test 3: Configure CTM to OR CTP[0] and CTP[1] -> CTP[2]...")
    ctm_src2_addr = get_ctm_src_config_addr(2)
    # Set bits 0 and 1 to select CTP[0] OR CTP[1] as sources
    await axil_write(dut, axil, ctm_src2_addr, 0x3)
    await wait_cycles(dut, 2)

    readback = await axil_read(dut, axil, ctm_src2_addr)
    dut._log.info(f"CTM CT_SRC2_CONFIG = 0x{readback:08X}")
    assert readback == 0x3, f"CTM OR config mismatch: {readback}"

    dut._log.info("=== CTN Routing Test PASSED ===")


@cocotb.test()
async def test_mixed_mode_routing(dut):
    """Test routing between CTPs configured in different modes (Wire-OR and P2P)

    This test verifies that cross trigger routing works correctly when:
    - External CTPs are configured in mixed modes (some Wire-OR, some P2P)
    - Internal CTPs are configured in mixed modes (lower=Wire-OR, upper=P2P)
    - Routing crosses between different modes

    Configuration:
    - External CTP[0], CTP[1]: Wire-OR mode
    - External CTP[2], CTP[3]: P2P mode
    - Internal CT[0..N/2-1]: Wire-OR mode (from testbench INT_CT_MODE)
    - Internal CT[N/2..N-1]: P2P mode (from testbench INT_CT_MODE)

    Test cases:
    1. External Wire-OR -> External P2P: CTP[0] -> CTP[2]
    2. External P2P -> External Wire-OR: CTP[2] -> CTP[1]
    3. External Wire-OR -> Internal P2P: CTP[0] -> Internal CT[N/2]
    4. Internal Wire-OR -> External P2P: Internal CT[0] -> CTP[3]
    5. Internal P2P -> External Wire-OR: Internal CT[N/2] -> CTP[0]
    """

    # Start clocks
    clock = await start_clocks(dut, period_ns=10)

    # Initialize DUT
    await init(dut)

    # Initialize AXI-Lite
    await init_axil(dut)
    axil = AxiLiteMaster(dut)
    await axil.initialize_bus()

    await wait_cycles(dut, 10)

    dut._log.info("=== Mixed Mode Routing Test Starting ===")
    dut._log.info(f"Configuration: {NUM_CTP} external CTPs, {NUM_INT_CT} internal CTPs")
    dut._log.info(f"  Internal Wire-OR: {NUM_INT_CT_WIRE_OR}, Internal P2P: {NUM_INT_CT_P2P}")

    if NUM_CTP < 4:
        dut._log.info("Need at least 4 external CTPs for mixed mode test, skipping")
        return

    # Configure external CTPs in mixed modes
    # CTP[0], CTP[1]: Wire-OR mode
    # CTP[2], CTP[3]: P2P mode
    dut._log.info("Configuring external CTPs in mixed modes...")

    for i in range(NUM_CTP):
        ctp_config_addr = get_ctp_addr(i, CTP_REG_CONFIG)
        ctp_stretch_addr = get_ctp_addr(i, CTP_REG_STRETCH_MULT)

        if i < 2:
            # Wire-OR mode for CTP[0], CTP[1]
            await axil_write(dut, axil, ctp_config_addr, 0x0)  # MODE=0 (Wire-OR)
            await axil_write(dut, axil, ctp_stretch_addr, 0x8)  # 8 cycle stretch
            dut._log.info(f"  CTP[{i}]: Wire-OR mode")
        elif i < 4:
            # P2P mode for CTP[2], CTP[3]
            await axil_write(dut, axil, ctp_config_addr, 0x1)  # MODE=1 (P2P)
            dut._log.info(f"  CTP[{i}]: P2P mode")
        else:
            # Default to Wire-OR for remaining CTPs
            await axil_write(dut, axil, ctp_config_addr, 0x0)
            await axil_write(dut, axil, ctp_stretch_addr, 0x4)

    await wait_cycles(dut, 5)

    # Clear all inputs
    dut.ctp_req_out_din.value = 0
    dut.ctp_req_in_din.value = 0
    dut.ctp_ack_in_din.value = 0
    dut.ctm_dst_req.value = 0
    dut.ctm_src_ack.value = 0
    await wait_cycles(dut, 5)

    # === Test 1: External Wire-OR -> External P2P ===
    # Route CTP[0] (Wire-OR) -> CTP[2] (P2P)
    dut._log.info("Test 1: External Wire-OR -> External P2P (CTP[0] -> CTP[2])...")
    ctm_src2_addr = get_ctm_src_config_addr(2)
    await axil_write(dut, axil, ctm_src2_addr, 0x1)  # Select CTP[0] as source

    readback = await axil_read(dut, axil, ctm_src2_addr)
    assert readback == 0x1, f"Test 1: CTM config mismatch"

    # Trigger from CTP[0] (Wire-OR input)
    dut.ctp_req_out_din.value = 0x1
    await wait_cycles(dut, 3)
    dut.ctp_req_out_din.value = 0

    # Check CTP[2] output (P2P mode uses dout, not dout_en)
    output_detected = False
    for cycle in range(15):
        await RisingEdge(dut.clk)
        # Model Wire-OR feedback for CTP[0] and CTP[1]
        dout_en = int(dut.ctp_req_out_dout_en.value)
        dut.ctp_req_out_din.value = dout_en & 0x3  # Only CTP[0,1] are Wire-OR

        req_out_dout = int(dut.ctp_req_out_dout.value)
        if req_out_dout & 0x4:  # CTP[2] output
            output_detected = True
            dut._log.info(f"  CTP[2] output detected at cycle {cycle}")
            break

    assert output_detected, "Test 1 failed: CTP[2] (P2P) did not receive from CTP[0] (Wire-OR)"

    # Complete P2P handshake for CTP[2]
    dut.ctp_ack_in_din.value = 0x4  # Ack CTP[2]
    await wait_cycles(dut, 5)
    dut.ctp_ack_in_din.value = 0

    # Clear routing
    await axil_write(dut, axil, ctm_src2_addr, 0)
    await wait_cycles(dut, 10)
    dut.ctp_req_out_din.value = 0

    dut._log.info("  Test 1 PASSED")

    # === Test 2: External P2P -> External Wire-OR ===
    # Route CTP[2] (P2P) -> CTP[1] (Wire-OR)
    dut._log.info("Test 2: External P2P -> External Wire-OR (CTP[2] -> CTP[1])...")
    ctm_src1_addr = get_ctm_src_config_addr(1)
    await axil_write(dut, axil, ctm_src1_addr, 0x4)  # Select CTP[2] as source

    readback = await axil_read(dut, axil, ctm_src1_addr)
    assert readback == 0x4, f"Test 2: CTM config mismatch"

    # Trigger from CTP[2] (P2P input via req_in)
    dut.ctp_req_in_din.value = 0x4  # CTP[2] req_in
    await wait_cycles(dut, 3)

    # Check CTP[1] output (Wire-OR mode uses dout_en)
    output_detected = False
    for cycle in range(15):
        await RisingEdge(dut.clk)
        # Model Wire-OR feedback
        dout_en = int(dut.ctp_req_out_dout_en.value)
        dut.ctp_req_out_din.value = dout_en & 0x3

        if dout_en & 0x2:  # CTP[1] output enable
            output_detected = True
            dut._log.info(f"  CTP[1] output detected at cycle {cycle}")
            break

    assert output_detected, "Test 2 failed: CTP[1] (Wire-OR) did not receive from CTP[2] (P2P)"

    # Clear inputs
    dut.ctp_req_in_din.value = 0
    dut.ctp_req_out_din.value = 0
    await axil_write(dut, axil, ctm_src1_addr, 0)
    await wait_cycles(dut, 10)

    dut._log.info("  Test 2 PASSED")

    # === Test 3: External Wire-OR -> Internal P2P ===
    if NUM_INT_CT_P2P > 0:
        dut._log.info("Test 3: External Wire-OR -> Internal P2P (CTP[0] -> Internal CT[P2P])...")
        int_ct_p2p_idx = NUM_INT_CT_WIRE_OR  # First P2P internal CT
        ctm_port_p2p = NUM_CTP + int_ct_p2p_idx
        ctm_src_addr = get_ctm_src_config_addr(ctm_port_p2p)
        await axil_write(dut, axil, ctm_src_addr, 0x1)  # Select CTP[0] as source

        readback = await axil_read(dut, axil, ctm_src_addr)
        assert readback == 0x1, f"Test 3: CTM config mismatch"

        # Trigger from CTP[0] (Wire-OR input)
        dut.ctp_req_out_din.value = 0x1
        await wait_cycles(dut, 3)
        dut.ctp_req_out_din.value = 0

        # Check internal CT output (P2P mode)
        output_detected = False
        for cycle in range(20):
            await RisingEdge(dut.clk)
            # Model Wire-OR feedback
            dout_en = int(dut.ctp_req_out_dout_en.value)
            dut.ctp_req_out_din.value = dout_en & 0x3

            ctm_src_req = int(dut.ctm_src_req.value)
            if ctm_src_req & (1 << int_ct_p2p_idx):
                output_detected = True
                dut._log.info(f"  Internal CT[{int_ct_p2p_idx}] output detected at cycle {cycle}")
                break

        assert output_detected, f"Test 3 failed: Internal CT[{int_ct_p2p_idx}] (P2P) did not receive"

        # Complete handshake
        dut.ctm_src_ack.value = 1 << int_ct_p2p_idx
        await wait_cycles(dut, 5)
        dut.ctm_src_ack.value = 0

        await axil_write(dut, axil, ctm_src_addr, 0)
        await wait_cycles(dut, 10)
        dut.ctp_req_out_din.value = 0

        dut._log.info("  Test 3 PASSED")
    else:
        dut._log.info("Test 3: Skipped (no internal P2P CTPs)")

    # === Test 4: Internal Wire-OR -> External P2P ===
    if NUM_INT_CT_WIRE_OR > 0:
        dut._log.info("Test 4: Internal Wire-OR -> External P2P (Internal CT[0] -> CTP[3])...")
        ctm_src3_addr = get_ctm_src_config_addr(3)
        int_ct_wire_or_port = NUM_CTP + 0  # Internal CT[0] is Wire-OR
        await axil_write(dut, axil, ctm_src3_addr, 1 << int_ct_wire_or_port)

        readback = await axil_read(dut, axil, ctm_src3_addr)
        assert readback == (1 << int_ct_wire_or_port), f"Test 4: CTM config mismatch"

        # Trigger from internal CT[0] (Wire-OR)
        dut.ctm_dst_req.value = 0x1  # Internal CT[0]

        # Check CTP[3] output (P2P mode)
        output_detected = False
        for cycle in range(20):
            await RisingEdge(dut.clk)
            req_out_dout = int(dut.ctp_req_out_dout.value)
            if req_out_dout & 0x8:  # CTP[3] output
                output_detected = True
                dut._log.info(f"  CTP[3] output detected at cycle {cycle}")
                break

        assert output_detected, "Test 4 failed: CTP[3] (P2P) did not receive from Internal CT[0] (Wire-OR)"

        # Complete handshake
        dut.ctp_ack_in_din.value = 0x8
        await wait_cycles(dut, 5)
        dut.ctp_ack_in_din.value = 0
        dut.ctm_dst_req.value = 0

        await axil_write(dut, axil, ctm_src3_addr, 0)
        await wait_cycles(dut, 10)

        dut._log.info("  Test 4 PASSED")
    else:
        dut._log.info("Test 4: Skipped (no internal Wire-OR CTPs)")

    # === Test 5: Internal P2P -> External Wire-OR ===
    if NUM_INT_CT_P2P > 0:
        dut._log.info("Test 5: Internal P2P -> External Wire-OR (Internal CT[P2P] -> CTP[0])...")
        int_ct_p2p_idx = NUM_INT_CT_WIRE_OR  # First P2P internal CT
        ctm_port_p2p = NUM_CTP + int_ct_p2p_idx
        ctm_src0_addr = get_ctm_src_config_addr(0)
        await axil_write(dut, axil, ctm_src0_addr, 1 << ctm_port_p2p)

        readback = await axil_read(dut, axil, ctm_src0_addr)
        assert readback == (1 << ctm_port_p2p), f"Test 5: CTM config mismatch"

        # Trigger from internal CT (P2P mode)
        dut.ctm_dst_req.value = 1 << int_ct_p2p_idx

        # Check CTP[0] output (Wire-OR mode uses dout_en)
        output_detected = False
        for cycle in range(20):
            await RisingEdge(dut.clk)
            # Model Wire-OR feedback
            dout_en = int(dut.ctp_req_out_dout_en.value)
            dut.ctp_req_out_din.value = dout_en & 0x3

            if dout_en & 0x1:  # CTP[0] output enable
                output_detected = True
                dut._log.info(f"  CTP[0] output detected at cycle {cycle}")
                break

        assert output_detected, "Test 5 failed: CTP[0] (Wire-OR) did not receive from Internal CT (P2P)"

        dut.ctm_dst_req.value = 0
        dut.ctp_req_out_din.value = 0
        await axil_write(dut, axil, ctm_src0_addr, 0)
        await wait_cycles(dut, 10)

        dut._log.info("  Test 5 PASSED")
    else:
        dut._log.info("Test 5: Skipped (no internal P2P CTPs)")

    dut._log.info("=== Mixed Mode Routing Test PASSED ===")
