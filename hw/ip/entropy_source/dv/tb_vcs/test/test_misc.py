# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Suite 5: Miscellaneous Tests

Low-priority tests for auxiliary features:
- Downsample rate configuration
"""

import cocotb
from cocotb.triggers import ClockCycles

from test.test_base import *
from test.test_config import DecorrelatorConfig, get_custom_config


@cocotb.test()
async def test_5_1_downsample_rate_configuration(dut):
    """
    TEST 5.1: Verify CTRL.DOWNSAMPLE_RATE correctly downsamples decorrelator output

    This test verifies the CTRL.DOWNSAMPLE_RATE[25:16] field functionality
    with downsample rate = 63 (1-in-64 downsampling).

    The feature drops samples from the decorrelator output before pushing to FIFO.

    RTL Behavior:
    - DOWNSAMPLE_RATE=N: Drop first N samples, then push 1-in-(N+1)
    - DOWNSAMPLE_RATE=63: Drop first 63 samples, then push 1-in-64

    Test Plan: TEST_PLAN.txt Suite 5, Test 5.1
    """

    dut._log.info("\n" + "=" * 80)
    dut._log.info("TEST 5.1: Downsample Rate Configuration (RATE=63)")
    dut._log.info("=" * 80 + "\n")

    # Test with downsample rate = 63 (1-in-64 downsampling)
    rate = 63
    description = "1-in-64 downsampling"

    dut._log.info("Test Configuration:")
    dut._log.info(f"  DOWNSAMPLE_RATE = {rate}")
    dut._log.info(f"  Description: {description}")
    dut._log.info("  Expected: Drop first 63 samples, then push every 64th sample\n")

    # ====================================================================
    # TEST CONFIGURATION
    # ====================================================================
    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            bypass_mask=0x0,  # All lanes decorrelate
            sample_clk_div=63,  # Divide by 64
        ),
        decorrelator_samples=200,  # Collect more samples for downsample testing
        downsample_rate=rate,  # Test downsample rate = 63
        fifo_verification_enable=True,  # Enable FIFO verification
    )

    # ====================================================================
    # PHASE 1: TESTBENCH CONFIGURATION
    # ====================================================================
    dut._log.info("[PHASE 1] Testbench Configuration")
    apb, mon, cfg = await configure_testbench(dut, cfg)
    dut._log.info("  Testbench configured\n")

    # ====================================================================
    # PHASE 2: DUT PROGRAMMING
    # ====================================================================
    dut._log.info("[PHASE 2] DUT Programming")
    dut._log.info(f"  Programming CTRL.DOWNSAMPLE_RATE={rate}")
    await program_dut_registers(dut, apb, cfg)

    # Verify CTRL.DOWNSAMPLE_RATE was written correctly
    ctrl_val = await reg_rd(apb, "CTRL")
    actual_rate = (ctrl_val >> 16) & 0x3FF
    assert actual_rate == rate, f"DOWNSAMPLE_RATE mismatch: wrote {rate}, read {actual_rate}"
    dut._log.info(f"  CTRL.DOWNSAMPLE_RATE = {actual_rate} (verified)")
    dut._log.info("  DUT programmed successfully\n")

    # ====================================================================
    # PHASE 3: SAMPLE COLLECTION
    # ====================================================================
    dut._log.info(f"[PHASE 3] Sample Collection ({cfg.decorrelator_samples} samples)")
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    dut._log.info(f"  Collected {cfg.decorrelator_samples} samples from compressor")
    dut._log.info(f"  Golden queue: {len(golden_queue)} entries\n")

    # ====================================================================
    # PHASE 4: FIFO READOUT VERIFICATION WITH DOWNSAMPLE
    # ====================================================================
    dut._log.info(f"[PHASE 4] FIFO Readout Verification (rate={rate})")
    await verify_fifo_readout(
        dut, apb, golden_queue, cfg.decorrelator_samples, downsample_rate=cfg.downsample_rate
    )
    dut._log.info("  FIFO verification passed\n")

    # ====================================================================
    # PHASE 5: VERIFY SAMPLE RATE REDUCTION
    # ====================================================================
    dut._log.info("[PHASE 5] Sample Rate Reduction Verification")

    # Disable ROs to freeze FIFO
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)
    await ClockCycles(dut.apb.pclk, 10)

    # Check final FIFO level
    fifo_status = await reg_rd(apb, "FIFO_STATUS")
    fifo_level = fifo_status & 0x7F

    # Calculate expected FIFO entries based on downsampling
    # For rate=63: drop first 63, then 1-in-64
    # Expected: (200 - 63) / 64 ≈ 2-3 samples
    remaining = cfg.decorrelator_samples - rate
    expected_fifo = remaining // (rate + 1)
    expected_min = max(0, expected_fifo - 2)  # Allow tolerance
    expected_max = expected_fifo + 2

    dut._log.info(f"  FIFO level: {fifo_level}")
    dut._log.info(f"  Expected range: {expected_min} to {expected_max}")
    dut._log.info(
        f"  Calculation: ({cfg.decorrelator_samples} - {rate}) / {rate + 1} ≈ {expected_fifo}"
    )

    # Verify FIFO level is in expected range
    assert expected_min <= fifo_level <= expected_max, (
        f"FIFO level {fifo_level} outside expected range [{expected_min}, {expected_max}]"
    )
    dut._log.info("  [PASS] FIFO level within expected range\n")

    # ====================================================================
    # PHASE 6: CHECKER VERIFICATION
    # ====================================================================
    dut._log.info("[PHASE 6] Checker Verification")
    await verify_checkers(dut)
    dut._log.info("  All checkers passed\n")

    # ========================================================================
    # FINAL TEST SUMMARY
    # ========================================================================
    dut._log.info("\n" + "=" * 80)
    dut._log.info("TEST 5.1 SUMMARY")
    dut._log.info("=" * 80)
    dut._log.info(f"[PASS] DOWNSAMPLE_RATE={rate} ({description}) - VERIFIED")
    dut._log.info("[PASS] CSR read/write functionality - VERIFIED")
    dut._log.info(f"[PASS] Sample rate reduction (~{rate + 1}x) - VERIFIED")
    dut._log.info("[PASS] FIFO level matches expected downsampled count - VERIFIED")
    dut._log.info("[PASS] All checkers (DECOR, COMP, FIFO) - PASSED")
    dut._log.info("\n[PASS] test_5_1_downsample_rate_configuration: Test completed successfully!")
    dut._log.info("=" * 80 + "\n")
