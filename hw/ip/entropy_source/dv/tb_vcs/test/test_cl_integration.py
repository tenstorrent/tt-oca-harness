# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
CL Integration Test - Minimal Connection Verification

This test verifies entropy_stream_data_o and entropy_stream_vld_o outputs
with minimal configuration and NO behavioral models required.

Test Strategy:
1. Disable all models (RO injection, checkers)
2. Configure decorrelator bypass mode
3. Initialize ring oscillators via RING_OSC_ENABLE toggle
4. Observe entropy_stream_data_o and entropy_stream_vld_o toggling

This demonstrates that with just:
- clk_i (APB clock)
- 2 APB register writes (DECORRELATOR_CTRL, RING_OSC_ENABLE)
- Simple RO initialization sequence (disable → wait → enable)

The entropy source will generate output on entropy_stream_data_o/vld_o
without needing any behavioral models or external clock input.
"""

import cocotb
from cocotb.triggers import RisingEdge

from test.test_base import *
from test.test_config import CompressorConfig, DecorrelatorConfig, ROConfig, get_custom_config


@cocotb.test()
async def test_cl_integration_minimal(dut):
    """
    Minimal CL integration test - Verify entropy outputs with no models.

    Configuration:
    - RO model injection: DISABLED (use real ring oscillators)
    - Decorrelator checker: DISABLED
    - Compressor checker: DISABLED
    - Clock mode: Internal sample clock ROs (default)

    Expected Result:
    - entropy_stream_vld_o pulses HIGH
    - entropy_stream_data_o shows changing values
    """

    # ========================================================================
    # TEST CONFIGURATION - Disable all models
    # ========================================================================
    cfg = get_custom_config(
        ro=ROConfig(
            inject_model=0,  # DISABLE RO model injection - use real ROs
            auto_randomize=False,  # No randomization needed
        ),
        decorrelator=DecorrelatorConfig(
            checker_enable=False  # Disable decorrelator checker
        ),
        compressor=CompressorConfig(
            checker_enable=False  # Disable compressor checker
        ),
        fifo_error_monitor_enable=False,  # Disable FIFO monitor for this test
    )

    dut._log.info("=" * 80)
    dut._log.info("CL INTEGRATION TEST - Minimal Configuration")
    dut._log.info("=" * 80)
    dut._log.info("Models: ALL DISABLED (using real ring oscillators)")
    dut._log.info("Clock Mode: Internal sample clock ROs (default)")
    dut._log.info("Decorrelator: BYPASS mode (no feedback)")
    dut._log.info("=" * 80)

    # ========================================================================
    # PHASE 1: Initialize (clocks + reset)
    # ========================================================================
    dut._log.info("\n[PHASE 1] Initialize clocks and reset")
    apb, mon = await init(dut, config=cfg)
    dut._log.info("  [OK] Clocks running, reset released")

    # ========================================================================
    # PHASE 2: Read Component ID (verify APB works)
    # ========================================================================
    dut._log.info("\n[PHASE 2] Verify APB interface")

    # Read COMPONENT_ID using symbolic name
    component_id = await reg_rd(apb, "COMPONENT_ID")
    dut._log.info(f"  Component ID (via register name) = 0x{component_id:08X}")
    assert component_id == 0x01000001, f"Expected 0x01000001, got 0x{component_id:08X}"

    # Read address 0x0 directly to confirm register mapping
    component_id_direct = await apb.read(0x0)
    dut._log.info(f"  Component ID (via addr 0x0) = 0x{component_id_direct:08X}")
    assert component_id_direct == 0x01000001, (
        f"Expected 0x01000001 at addr 0x0, got 0x{component_id_direct:08X}"
    )

    dut._log.info("  [OK] APB interface verified")

    # ========================================================================
    # PHASE 3: Configure Bypass Decorrelator Mode and Initialize ROs
    # ========================================================================
    dut._log.info("\n[PHASE 3] Configure bypass decorrelator mode and initialize ROs")

    # Configure DECORRELATOR_CTRL for bypass mode
    # - BYPASS[11:0] = 0xFFF: Bypass all 12 decorrelators (no feedback loop)
    # - SAMPLE_CLK_DIV[31:12] = 63: Sample clock divider (actual division = value + 1 = 64)
    #   This sets the decorrelator sampling rate to clk/64
    decorr_ctrl = (63 << 12) | 0xFFF
    await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl)
    readback = await reg_rd(apb, "DECORRELATOR_CTRL")
    dut._log.info(f"  DECORRELATOR_CTRL = 0x{readback:08X}")
    dut._log.info(f"    BYPASS[11:0] = 0x{readback & 0xFFF:03X} (all decorrelators bypassed)")
    dut._log.info(f"    SAMPLE_CLK_DIV[31:12] = {(readback >> 12) & 0xFFFFF} (div-64 sampling)")

    # Ring Oscillator Enable Sequence - CRITICAL for avoiding X propagation
    #
    # Problem: Ring oscillators have combinational feedback loops that can get stuck
    # in an X (unknown) state. Once in X state, the loop never resolves.
    #
    # Solution: Toggle RING_OSC_ENABLE to break X propagation
    # 1. Disable all ROs (RING_OSC_ENABLE = 0x00000000)
    # 2. Wait 100 cycles to allow all internal states to settle
    # 3. Enable all ROs (RING_OSC_ENABLE = 0x00FFFFFF)
    #
    # This sequence forces the RO feedback loops to initialize to a known state
    # (disabled = 0), breaking any X propagation. When re-enabled, the ROs start
    # from a clean state and can oscillate normally.

    # Step 1: Disable all ring oscillators
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)

    # Step 2: Wait for internal states to settle (100 APB clock cycles)
    for _ in range(100):
        await RisingEdge(dut.apb.pclk)

    # Step 3: Enable all 24 oscillators (12 noise ROs + 12 sample clock ROs)
    # ENABLE[11:0] = 0xFFF: Enable 12 noise ring oscillators
    # SAMPLE_CLK_ENABLE[23:12] = 0xFFF: Enable 12 sample clock ring oscillators
    # Note: RING_OSC_CTRL defaults to 0xFFF (use internal sample clock ROs)
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00FFFFFF)
    ring_osc_enable = await reg_rd(apb, "RING_OSC_ENABLE")
    dut._log.info(f"  RING_OSC_ENABLE = 0x{ring_osc_enable:08X} (all 24 ROs enabled)")
    dut._log.info("  [OK] DUT configured (bypass decorrelator mode, internal sample clocks)")

    # ========================================================================
    # PHASE 4: Monitor FIFO Status (verify data path)
    # ========================================================================
    dut._log.info("\n[PHASE 4] Monitor FIFO status (verify data path)")

    # Read FIFO_STATUS periodically to verify FIFO is being written
    fifo_status_samples = []
    for sample_num in range(5):
        # Wait 100 cycles between samples
        for _ in range(100):
            await RisingEdge(dut.apb.pclk)

        # Read FIFO_STATUS register (0x24)
        fifo_status = await reg_rd(apb, "FIFO_STATUS")
        level = fifo_status & 0x7F  # bits[6:0]
        wptr = (fifo_status >> 8) & 0x1F  # bits[12:8]
        rptr = (fifo_status >> 16) & 0x1F  # bits[20:16]

        fifo_status_samples.append({"level": level, "wptr": wptr, "rptr": rptr})
        dut._log.info(f"  Sample {sample_num}: LEVEL={level}, WPTR={wptr}, RPTR={rptr}")

    # Verify FIFO is being written
    initial_level = fifo_status_samples[0]["level"]
    final_level = fifo_status_samples[-1]["level"]
    dut._log.info(f"  FIFO level changed: {initial_level} -> {final_level}")

    # Check that FIFO level increased (or stayed high if already full)
    assert final_level > 0, "FIFO level is 0 - no entropy generated!"
    dut._log.info(f"  [OK] FIFO receiving data (level={final_level})")

    # Check that write pointer advanced (wrapped around is OK)
    initial_wptr = fifo_status_samples[0]["wptr"]
    final_wptr = fifo_status_samples[-1]["wptr"]
    wptr_changed = initial_wptr != final_wptr
    dut._log.info(f"  Write pointer: {initial_wptr} -> {final_wptr} (changed={wptr_changed})")
    assert wptr_changed or final_level >= 60, "Write pointer not advancing and FIFO not full!"
    dut._log.info("  [OK] Write pointer advancing")

    # Read pointer should stay at 0 (we haven't read from FIFO yet)
    final_rptr = fifo_status_samples[-1]["rptr"]
    assert final_rptr == 0, f"Read pointer moved unexpectedly: {final_rptr}"
    dut._log.info("  [OK] Read pointer stable at 0 (no FIFO reads)")

    # Read some FIFO data to verify it's not all zeros
    dut._log.info("\n  Reading FIFO data to verify entropy values...")
    num_reads = min(10, final_level)  # Read up to 10 words or available FIFO level
    fifo_data = []
    zero_count = 0

    for i in range(num_reads):
        data = await reg_rd(apb, "FIFO_RDATA")
        fifo_data.append(data)
        if data == 0x00000000:
            zero_count += 1
        if i < 5:  # Log first 5 values
            dut._log.info(f"    FIFO[{i}] = 0x{data:08X}")

    # Verify not all zeros
    assert zero_count < num_reads, f"All FIFO data is zero! ({zero_count}/{num_reads} reads)"
    dut._log.info(
        f"  [OK] FIFO data verified: {num_reads} reads, {zero_count} zeros, {num_reads - zero_count} non-zero"
    )

    # Verify FIFO read pointer advanced
    fifo_status_after_read = await reg_rd(apb, "FIFO_STATUS")
    rptr_after = (fifo_status_after_read >> 16) & 0x1F
    assert rptr_after == num_reads, f"Read pointer mismatch: expected {num_reads}, got {rptr_after}"
    dut._log.info(f"  [OK] Read pointer advanced to {rptr_after} after {num_reads} reads")

    # ========================================================================
    # PHASE 5: Monitor entropy_stream outputs
    # ========================================================================
    dut._log.info("\n[PHASE 5] Monitor entropy_stream_data_o and entropy_stream_vld_o")

    # Wait and observe entropy_stream_vld_o
    valid_count = 0
    data_values = []
    timeout_cycles = 1000

    dut._log.info(f"  Monitoring for {timeout_cycles} clock cycles...")

    for cycle in range(timeout_cycles):
        await RisingEdge(dut.apb.pclk)

        # Read entropy stream outputs
        vld = int(dut.entropy_stream_vld.value)
        data = int(dut.entropy_stream_data.value)

        if vld:
            valid_count += 1
            data_values.append(data)
            if valid_count <= 10:  # Print first 10 samples
                dut._log.info(f"    Cycle {cycle}: entropy_stream_vld=1, data=0x{data:08X}")

    # ========================================================================
    # PHASE 6: Verify Results
    # ========================================================================
    dut._log.info("\n[PHASE 6] Verify results")
    dut._log.info(f"  Valid pulses detected: {valid_count}")
    dut._log.info(f"  Unique data values: {len(set(data_values))}")

    # Check that we got at least some valid pulses
    assert valid_count > 0, f"No entropy_stream_vld pulses detected in {timeout_cycles} cycles!"
    dut._log.info(f"  [OK] entropy_stream_vld_o toggled {valid_count} times")

    # Check that data is changing (not stuck)
    unique_values = len(set(data_values))
    assert unique_values > 1, f"Data stuck! Only saw {unique_values} unique value(s)"
    dut._log.info(f"  [OK] entropy_stream_data_o changing ({unique_values} unique values)")

    # Check that data is not stuck at 0x00000000 or 0xFFFFFFFF
    if 0x00000000 in data_values:
        zero_count = data_values.count(0x00000000)
        dut._log.info(f"  [INFO] Saw 0x00000000 {zero_count} times")
        assert zero_count < valid_count, "Data stuck at 0x00000000!"

    if 0xFFFFFFFF in data_values:
        ones_count = data_values.count(0xFFFFFFFF)
        dut._log.info(f"  [INFO] Saw 0xFFFFFFFF {ones_count} times")
        assert ones_count < valid_count, "Data stuck at 0xFFFFFFFF!"

    # ========================================================================
    # TEST SUMMARY
    # ========================================================================
    dut._log.info("\n" + "=" * 80)
    dut._log.info("CL INTEGRATION TEST: PASS")
    dut._log.info("=" * 80)
    dut._log.info("Summary:")
    dut._log.info("  - APB interface: Working (verified 0x000 = 0x01000001)")
    dut._log.info("  - Configuration: 2 APB writes (DECORRELATOR_CTRL, RING_OSC_ENABLE)")
    dut._log.info("  - Clock source: Internal sample clock ROs (default)")
    dut._log.info(f"  - FIFO level: {initial_level} -> {final_level} (data path working)")
    dut._log.info(f"  - FIFO write pointer: {initial_wptr} -> {final_wptr} (advancing)")
    dut._log.info(f"  - FIFO read: {num_reads} words, {num_reads - zero_count} non-zero values")
    dut._log.info(f"  - FIFO read pointer: 0 -> {rptr_after} (correct)")
    dut._log.info(f"  - entropy_stream_vld_o: Toggling ({valid_count} pulses)")
    dut._log.info(f"  - entropy_stream_data_o: Changing ({unique_values} unique values)")
    dut._log.info("  - Models used: NONE (real ring oscillators)")
    dut._log.info("=" * 80)

    # Sample data for documentation
    if len(data_values) >= 5:
        dut._log.info("\nSample entropy_stream data (first 5 values):")
        for i, val in enumerate(data_values[:5]):
            dut._log.info(f"  [{i}] 0x{val:08X}")

    if len(fifo_data) >= 5:
        dut._log.info("\nSample FIFO data (first 5 values):")
        for i, val in enumerate(fifo_data[:5]):
            dut._log.info(f"  [{i}] 0x{val:08X}")


@cocotb.test()
async def test_cl_integration_default_config(dut):
    """
    Default Configuration Test - Verify FIFO control path with ZERO configuration.

    This is the absolute minimum smoke test. Uses all register defaults with
    ZERO configuration writes. Only verifies FIFO control path (level, pointers),
    not data values.

    Configuration:
    - RO model injection: DISABLED (use real ring oscillators)
    - All registers: RESET DEFAULTS
    - Register writes: ZERO
    - Decorrelator mode: Normal (feedback active, not bypass)
    - Clock mode: Internal sample clock ROs (default)

    Expected Result:
    - FIFO level increases (control path works)
    - Write pointer advances (control path works)
    - Read pointer stays at 0 (control path works)
    - Data values: Not checked (may be X in simulation)

    Key Insight:
    FIFO control logic (counters/pointers) works independently of data values.
    Even if data path contains X's from RO feedback loops, the control path
    functions correctly and we can verify FIFO operation via status register.
    """

    # ========================================================================
    # TEST CONFIGURATION - Disable all models, use all defaults
    # ========================================================================
    cfg = get_custom_config(
        ro=ROConfig(
            inject_model=0,  # DISABLE RO model injection - use real ROs
            auto_randomize=False,  # No randomization needed
        ),
        decorrelator=DecorrelatorConfig(
            checker_enable=False  # Disable decorrelator checker
        ),
        compressor=CompressorConfig(
            checker_enable=False  # Disable compressor checker
        ),
        fifo_error_monitor_enable=False,  # Disable FIFO monitor for this test
    )

    dut._log.info("=" * 80)
    dut._log.info("CL INTEGRATION TEST - Default Configuration (Control Path Only)")
    dut._log.info("=" * 80)
    dut._log.info("Models: ALL DISABLED (using real ring oscillators)")
    dut._log.info("Configuration: ALL DEFAULTS (ZERO register writes)")
    dut._log.info("Decorrelator: NORMAL mode (feedback active)")
    dut._log.info("Verification: FIFO control path only (level/pointers, not data)")
    dut._log.info("=" * 80)

    # ========================================================================
    # PHASE 1: Initialize (clocks + reset)
    # ========================================================================
    dut._log.info("\n[PHASE 1] Initialize clocks and reset")
    apb, mon = await init(dut, config=cfg)
    dut._log.info("  [OK] Clocks running, reset released")

    # ========================================================================
    # PHASE 2: Wait for System Stabilization
    # ========================================================================
    dut._log.info("\n[PHASE 2] Wait for system stabilization")
    dut._log.info("  Waiting 1000 ns (100 cycles) for ROs and logic to stabilize...")
    for _ in range(100):
        await RisingEdge(dut.apb.pclk)
    dut._log.info("  [OK] System stabilized with default configuration")

    # ========================================================================
    # PHASE 3: Read Component ID (verify APB works)
    # ========================================================================
    dut._log.info("\n[PHASE 3] Verify APB interface")

    # Read COMPONENT_ID using symbolic name
    component_id = await reg_rd(apb, "COMPONENT_ID")
    dut._log.info(f"  Component ID (via register name) = 0x{component_id:08X}")
    assert component_id == 0x01000001, f"Expected 0x01000001, got 0x{component_id:08X}"

    # Read address 0x0 directly to confirm register mapping
    component_id_direct = await apb.read(0x0)
    dut._log.info(f"  Component ID (via addr 0x0) = 0x{component_id_direct:08X}")
    assert component_id_direct == 0x01000001, (
        f"Expected 0x01000001 at addr 0x0, got 0x{component_id_direct:08X}"
    )

    dut._log.info("  [OK] APB interface verified")

    # ========================================================================
    # PHASE 3: Monitor FIFO Status
    # ========================================================================
    dut._log.info("\n[PHASE 3] Monitor FIFO status (verify control path)")
    dut._log.info("  Note: Data may contain X's from RO feedback loops (simulation only)")
    dut._log.info("        Control path (LEVEL, WPTR, RPTR) works independently of data values")

    # Read FIFO_STATUS periodically to verify FIFO is being written
    # Note: Expect slower rate than bypass mode because decorrelator is
    # in normal mode with feedback loops active (not bypassed)
    fifo_status_samples = []
    for sample_num in range(5):
        # Wait 100 cycles between samples
        for _ in range(100):
            await RisingEdge(dut.apb.pclk)

        # Read FIFO_STATUS register (0x24)
        fifo_status = await reg_rd(apb, "FIFO_STATUS")
        level = fifo_status & 0x7F  # bits[6:0]
        wptr = (fifo_status >> 8) & 0x1F  # bits[12:8]
        rptr = (fifo_status >> 16) & 0x1F  # bits[20:16]

        fifo_status_samples.append({"level": level, "wptr": wptr, "rptr": rptr})
        dut._log.info(f"  Sample {sample_num}: LEVEL={level}, WPTR={wptr}, RPTR={rptr}")

    # Verify FIFO is being written
    initial_level = fifo_status_samples[0]["level"]
    final_level = fifo_status_samples[-1]["level"]
    dut._log.info(f"  FIFO level changed: {initial_level} -> {final_level}")

    # Check that FIFO level increased (or stayed high if already full)
    assert final_level > 0, "FIFO level is 0 - no entropy generated!"
    dut._log.info(f"  [OK] FIFO receiving data (level={final_level})")

    # Check that write pointer advanced (wrapped around is OK)
    initial_wptr = fifo_status_samples[0]["wptr"]
    final_wptr = fifo_status_samples[-1]["wptr"]
    wptr_changed = initial_wptr != final_wptr
    dut._log.info(f"  Write pointer: {initial_wptr} -> {final_wptr} (changed={wptr_changed})")
    assert wptr_changed or final_level >= 60, "Write pointer not advancing and FIFO not full!"
    dut._log.info("  [OK] Write pointer advancing")

    # Read pointer should stay at 0 (we haven't read from FIFO)
    final_rptr = fifo_status_samples[-1]["rptr"]
    assert final_rptr == 0, f"Read pointer moved unexpectedly: {final_rptr}"
    dut._log.info("  [OK] Read pointer stable at 0 (no FIFO reads)")

    # ========================================================================
    # TEST SUMMARY
    # ========================================================================
    dut._log.info("\n" + "=" * 80)
    dut._log.info("DEFAULT CONFIGURATION TEST: PASS")
    dut._log.info("=" * 80)
    dut._log.info("Summary:")
    dut._log.info("  - APB interface: Working (verified 0x000 = 0x01000001)")
    dut._log.info("  - Configuration writes: ZERO (pure defaults)")
    dut._log.info("  - Decorrelator mode: Normal (with feedback loops)")
    dut._log.info("  - Clock source: Internal sample clock ROs (default)")
    dut._log.info("  - FIFO control path: WORKING")
    dut._log.info(f"    * FIFO level: {initial_level} -> {final_level}")
    dut._log.info(f"    * Write pointer: {initial_wptr} -> {final_wptr} (advancing)")
    dut._log.info(f"    * Read pointer: {final_rptr} (stable)")
    dut._log.info("  - Data path: Not verified (may contain X's in simulation)")
    dut._log.info("  - Configuration: ALL DEFAULTS WORK FOR CONTROL PATH")
    dut._log.info("=" * 80)
    dut._log.info("\nNote: Control path (counters/pointers) independent of data values")
    dut._log.info("      Data may be X in simulation but FIFO control logic still functions")
