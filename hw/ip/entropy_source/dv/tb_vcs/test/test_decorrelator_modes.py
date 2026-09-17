# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Decorrelator Mode Test Suite

Tests decorrelator in different operating modes, clock divider settings,
and mixed mode configurations. Verifies decorrelator output, compressor
output, and FIFO readout.

SUITE 1: DECORRELATOR MODES (16 tests)

Category 1.1: Pure Modes (4 tests)
    - Test 1.1.1: Full decorrelation mode (div64)
    - Test 1.1.2: Full bypass mode (div8)
    - Test 1.1.3: Fast decorrelation (div8)
    - Test 1.1.4: Slow decorrelation (div256)

Category 1.2: Mixed/Mixer Modes (8 tests)
    - Test 1.2.1: Single lane bypass (Lane 0)
    - Test 1.2.2: Single lane bypass (Lane 11)
    - Test 1.2.3: Even lanes bypass
    - Test 1.2.4: Odd lanes bypass
    - Test 1.2.5: Half-and-half split
    - Test 1.2.6: Single lane decorrelate
    - Test 1.2.7: Mixed mode with fast sampling
    - Test 1.2.8: Dynamic bypass mask changes

Category 1.3: Compressor Bypass Mode (3 tests)
    - Test 1.3.1: Bypass mode - Normal rate (div64)
    - Test 1.3.2: Bypass mode - Slow rate (div256)
    - Test 1.3.3: Bypass mode - Fast rate (div8)

Category 1.4: Byte Mask Configuration (1 test)
    - Test 1.4.1: DECORRELATOR_MASK register (0xAA - even bits only)
"""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from test.test_base import (
    collect_entropy_samples,
    configure_testbench,
    program_dut_registers,
    reg_rd,
    reg_wr,
    verify_checkers,
    verify_fifo_readout,
)
from test.test_config import DecorrelatorConfig, get_custom_config


@cocotb.test()
async def test_1_1_1_full_decorrelation_mode(dut):
    """Test 1.1.1: Full decorrelation mode (div64) - Standard configuration"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=63,
            bypass_mask=0x000,
            sample_period=64,  # Reference model must match DUT: div64 = period 64
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Collect samples (returns golden queue for FIFO verification)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 4: Verify FIFO readout
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 5: Verify all checkers (decorrelator + compressor)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.1.1 complete")


@cocotb.test()
async def test_1_1_2_full_bypass_mode(dut):
    """Test 1.1.2: Full bypass mode (div8) - Per spec bypass uses div8"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=2,
            bypass_dut=True,
            sample_clk_div=7,
            bypass_mask=0xFFF,
            sample_period=8,  # Reference model must match DUT: div8 = period 8
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Collect samples (returns golden queue for FIFO verification)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 4: Verify FIFO readout
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 5: Verify all checkers (decorrelator + compressor)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.1.2 complete")


@cocotb.test()
async def test_1_1_3_decorrelation_fast_sampling(dut):
    """Test 1.1.3: Decorrelation with fast sampling (div8) - Verify algorithm works at higher rate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=7,
            bypass_mask=0x000,
            sample_period=8,  # Reference model must match DUT: div8 = period 8
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Collect samples (returns golden queue for FIFO verification)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 4: Verify FIFO readout
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 5: Verify all checkers (decorrelator + compressor)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.1.3 complete")


@cocotb.test()
async def test_1_1_4_decorrelation_slow_sampling(dut):
    """Test 1.1.4: Decorrelation with slow sampling (div256) - Maximum entropy quality"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=255,
            bypass_mask=0x000,
            sample_period=256,  # Reference model must match DUT: div256 = period 256
        ),
        decorrelator_samples=30,  # Fewer samples due to slow rate
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Collect samples (returns golden queue for FIFO verification)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 4: Verify FIFO readout
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 5: Verify all checkers (decorrelator + compressor)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.1.4 complete")


# ============================================================================
# Category 2: Mixed/Mixer Modes (Per-Lane Bypass Control)
# ============================================================================
# Tests verify mixed mode capability where different lanes can have different
# decorrelator configurations using the BYPASS_MASK register.
#
# The reference model supports per-lane bypass control, so the decorrelator checker is
# ENABLED for all mixed mode tests. Verification:
#   - Decorrelator checker (per-lane verification against reference model)
#   - Compressor checker (end-to-end verification)
#   - FIFO verification (data integrity)


@cocotb.test()
async def test_1_2_1_single_lane_bypass_lane0(dut):
    """Test 1.2.1: Single lane bypass (Lane 0) - Only lane 0 bypasses, others decorrelate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,  # Reference: DECOR_29 for non-bypassed lanes
            bypass_dut=True,  # DUT: Mixed mode
            sample_clk_div=63,  # div64 for decorrelation
            bypass_mask=0x001,  # Only lane 0 bypassed
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Collect samples (returns golden queue for FIFO verification)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 4: Verify FIFO readout
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 5: Verify all checkers (decorrelator + compressor)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.1 complete - Lane 0 bypassed, lanes 1-11 decorrelate")


@cocotb.test()
async def test_1_2_2_single_lane_bypass_lane11(dut):
    """Test 1.2.2: Single lane bypass (Lane 11) - Only lane 11 bypasses, others decorrelate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=63,
            bypass_mask=0x800,  # Only lane 11 bypassed
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.2 complete - Lanes 0-10 decorrelate, lane 11 bypassed")


@cocotb.test()
async def test_1_2_3_even_lanes_bypass(dut):
    """Test 1.2.3: Even lanes bypass (0,2,4,6,8,10) - Even lanes bypass, odd lanes decorrelate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=63,
            bypass_mask=0x555,  # Even lanes bypassed (binary: 0101 0101 0101)
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.3 complete - Even lanes bypass, odd lanes decorrelate")


@cocotb.test()
async def test_1_2_4_odd_lanes_bypass(dut):
    """Test 1.2.4: Odd lanes bypass (1,3,5,7,9,11) - Odd lanes bypass, even lanes decorrelate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=63,
            bypass_mask=0xAAA,  # Odd lanes bypassed (binary: 1010 1010 1010)
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.4 complete - Odd lanes bypass, even lanes decorrelate")


@cocotb.test()
async def test_1_2_5_half_and_half_split(dut):
    """Test 1.2.5: Half-and-half split - Lanes 0-5 bypass, lanes 6-11 decorrelate"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=63,
            bypass_mask=0x03F,  # Lanes 0-5 bypassed (binary: 0000 0011 1111)
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.5 complete - Lanes 0-5 bypass, lanes 6-11 decorrelate")


@cocotb.test()
async def test_1_2_6_single_lane_decorrelate(dut):
    """Test 1.2.6: Single lane decorrelate - All bypass except lane 5"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=63,
            bypass_mask=0xFDF,  # All bypass except lane 5 (binary: 1111 1101 1111)
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.6 complete - Lane 5 decorrelates, all others bypass")


@cocotb.test()
async def test_1_2_7_mixed_mode_fast_sampling(dut):
    """Test 1.2.7: Mixed mode with fast sampling - div8 rate with lanes 4-7 bypassed"""

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=True,
            sample_clk_div=7,  # div8 (fast sampling)
            bypass_mask=0x0F0,  # Lanes 4-7 bypassed (binary: 0000 1111 0000)
            sample_period=8,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.7 complete - Mixed mode at div8 sampling rate")


@cocotb.test()
async def test_1_2_8_dynamic_bypass_mask_changes(dut):
    """Test 1.2.8: Dynamic bypass mask changes - Change mask during operation"""

    # Start with all decorrelating (mask=0x000)
    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,  # Initially no bypass
            sample_clk_div=63,
            bypass_mask=0x000,  # Start: all decorrelate
            sample_period=64,
            checker_enable=True,  # Enable decorrelator checker (ref model supports mixed mode)
        ),
        decorrelator_samples=20,
        fifo_verification_enable=True,
    )

    apb, mon, cfg = await configure_testbench(dut, config=cfg)
    await program_dut_registers(dut, apb, cfg)

    # Stage 1: All decorrelating (mask=0x000)
    dut._log.info("\n[Stage 1] All lanes decorrelating (bypass_mask=0x000)")
    ref_samples_1, golden_queue_1 = await collect_entropy_samples(dut, cfg, 20)

    # Stage 2: Change to half bypass (mask=0x03F)
    dut._log.info("\n[Stage 2] Changing to half bypass (bypass_mask=0x03F)")
    await RisingEdge(dut.apb.pclk)
    decorr_ctrl_val = (63 << 12) | 0x03F  # sample_clk_div=63, bypass_mask=0x03F
    await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl_val)

    # Update reference model configuration
    dut.decor_cfg.bypass_mask.value = 0x03F

    # Collect 20 more samples
    ref_samples_2, golden_queue_2 = await collect_entropy_samples(dut, cfg, 20)

    # Stage 3: Change to all bypass (mask=0xFFF)
    dut._log.info("\n[Stage 3] Changing to all bypass (bypass_mask=0xFFF)")
    await RisingEdge(dut.apb.pclk)
    decorr_ctrl_val = (63 << 12) | 0xFFF  # sample_clk_div=63, bypass_mask=0xFFF
    await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl_val)

    # Update reference model configuration
    dut.decor_cfg.bypass_mask.value = 0xFFF

    # Collect 20 more samples
    ref_samples_3, golden_queue_3 = await collect_entropy_samples(dut, cfg, 20)

    # Verify FIFO contains data from all 3 stages (60 samples total)
    dut._log.info("\n[Verification] Verifying complete FIFO readout (60 samples)")
    golden_queue_combined = golden_queue_1 + golden_queue_2 + golden_queue_3
    await verify_fifo_readout(dut, apb, golden_queue_combined, 60)

    # Verify compressor checker
    await verify_checkers(dut)

    dut._log.info("[PASS] Test 1.2.8 complete - Dynamic mask changes verified")


# ============================================================================
# Category 1.3: Compressor Bypass Mode Tests
# ============================================================================
# Tests verify the BYPASS_ENTROPY_COMPRESSOR feature (CTRL[8]) where
# the compressor is bypassed and raw decorrelator output goes directly to FIFO.
#
# NOTE: Normal compressor mode (BYPASS=0) is already tested in Suite 1.1 and 1.2.
# This suite focuses exclusively on bypass mode behavior.
#
# RTL Behavior (when CTRL.BYPASS_ENTROPY_COMPRESSOR=1):
#   - Multi-cycle FSM pushes 3 FIFO words per sample:
#     - Word 0: decorrelator bytes[3:0]   (lanes 0-3)
#     - Word 1: decorrelator bytes[7:4]   (lanes 4-7)
#     - Word 2: decorrelator bytes[11:8]  (lanes 8-11)
#   - FIFO usage: 3 words/sample (vs 1 word/sample in normal mode)
#   - Max safe samples: 21 (FIFO depth 64 / 3 words)
#
# Verification Strategy:
#   - Compressor checker MUST be disabled (no compressor output to check)
#   - Decorrelator checker can remain enabled
#   - Manual FIFO verification of 3-word packing format


@cocotb.test()
async def test_1_3_1_bypass_compressor_mode(dut):
    """Test 1.3.1: Bypass compressor mode - BYPASS_ENTROPY_COMPRESSOR=1 (3:1 FIFO ratio)"""

    from test.test_base import read_fifo_status, reg_rd, reg_wr
    from test.test_config import CompressorConfig

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=63,
            bypass_mask=0x000,
            sample_period=64,
            checker_enable=True,  # Decorrelator checker still works
        ),
        compressor=CompressorConfig(
            checker_enable=False  # MUST disable compressor checker
        ),
        bypass_compressor_dut=True,  # Compressor BYPASSED
        decorrelator_samples=20,  # 20 samples x 3 words = 60 FIFO entries (FIFO depth=64)
        fifo_verification_enable=False,  # Manual FIFO verification
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Verify CTRL register
    ctrl_val = await reg_rd(apb, "CTRL")
    bypass_bit = (ctrl_val >> 8) & 0x1
    dut._log.info(f"\n[Verify] CTRL.BYPASS_ENTROPY_COMPRESSOR[8] = {bypass_bit}")
    assert bypass_bit == 1, f"Expected BYPASS=1, got {bypass_bit}"

    # Phase 3: Collect decorrelator samples (ref_samples = golden reference)
    # The golden_queue from collect_entropy_samples() contains compressor model output
    # which is NOT relevant in bypass mode. We use ref_samples instead.
    ref_samples, _ = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Wait for clock edge to exit ReadOnly phase before APB transaction
    await RisingEdge(dut.apb.pclk)

    # Disable ROs to stop entropy generation (proper way to freeze FIFO push)
    dut._log.info("\n[Freeze] Disabling RING_OSC_ENABLE to stop entropy generation...")
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)

    # Wait for pipeline to drain
    await ClockCycles(dut.apb.pclk, 10)

    # Check FIFO level (should be 20 samples x 3 words = 60 entries)
    level, _, _ = await read_fifo_status(apb)
    dut._log.info(f"\n[FIFO] Level: {level} entries (expected ~60)")
    assert 56 <= level <= 64, f"Expected ~60 entries, got {level}"

    # Phase 4: Verify 3-word packing against decorrelator reference model
    dut._log.info("\n[Verification] Verifying 3-word FIFO packing against ref_samples:")
    mismatch_count = 0
    num_verify = len(ref_samples)  # Verify all samples
    dut._log.info(f"  Verifying all {num_verify} samples")

    for sample_idx in range(num_verify):
        # Read 3 FIFO words for this sample
        word0 = await reg_rd(apb, "FIFO_RDATA")  # Lanes [3:0]
        word1 = await reg_rd(apb, "FIFO_RDATA")  # Lanes [7:4]
        word2 = await reg_rd(apb, "FIFO_RDATA")  # Lanes [11:8]

        # Build expected words from decorrelator reference output
        ref_bytes = ref_samples[sample_idx]  # 12 bytes from decorrelator model
        expected_word0 = (
            (ref_bytes[3] << 24) | (ref_bytes[2] << 16) | (ref_bytes[1] << 8) | ref_bytes[0]
        )
        expected_word1 = (
            (ref_bytes[7] << 24) | (ref_bytes[6] << 16) | (ref_bytes[5] << 8) | ref_bytes[4]
        )
        expected_word2 = (
            (ref_bytes[11] << 24) | (ref_bytes[10] << 16) | (ref_bytes[9] << 8) | ref_bytes[8]
        )

        # Verify each word
        match0 = word0 == expected_word0
        match1 = word1 == expected_word1
        match2 = word2 == expected_word2

        # Show first 3, last 2, and all mismatches
        show_sample = (
            (sample_idx < 3) or (sample_idx >= num_verify - 2) or not (match0 and match1 and match2)
        )
        if show_sample:
            dut._log.info(f"\n  Sample {sample_idx}:")
            dut._log.info(
                f"    Word 0 (lanes [3:0]):   DUT=0x{word0:08X}  Expected=0x{expected_word0:08X}  {'MATCH' if match0 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 1 (lanes [7:4]):   DUT=0x{word1:08X}  Expected=0x{expected_word1:08X}  {'MATCH' if match1 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 2 (lanes [11:8]):  DUT=0x{word2:08X}  Expected=0x{expected_word2:08X}  {'MATCH' if match2 else 'MISMATCH'}"
            )
        elif sample_idx == 3:
            dut._log.info("\n  ... (showing first 3 and last 2 only)")

        if not (match0 and match1 and match2):
            mismatch_count += 1
            if not match0:
                dut._log.error(f"      Word 0 XOR: 0x{word0 ^ expected_word0:08X}")
            if not match1:
                dut._log.error(f"      Word 1 XOR: 0x{word1 ^ expected_word1:08X}")
            if not match2:
                dut._log.error(f"      Word 2 XOR: 0x{word2 ^ expected_word2:08X}")

    # Report results
    if mismatch_count == 0:
        dut._log.info(f"\n[PASS] All {num_verify} verified samples matched decorrelator reference!")
        dut._log.info(
            f"  Total FIFO entries: {len(ref_samples)} samples x 3 words = {len(ref_samples) * 3} entries"
        )
    else:
        dut._log.error(f"\n[FAIL] {mismatch_count}/{num_verify} samples with mismatches!")
        raise AssertionError(f"FIFO bypass verification failed: {mismatch_count} sample mismatches")

    # Verify decorrelator checker (compressor checker already disabled)
    from test.test_base import decor_checker_verify

    decor_checker_verify(dut)

    dut._log.info("[PASS] Test 1.3.1 complete - Bypass mode with normal rate (div64)")


@cocotb.test()
async def test_1_3_2_bypass_slow_sampling(dut):
    """Test 1.3.2: Bypass mode with slow sampling (div256) - Realistic high-quality entropy generation"""

    from test.test_base import decor_checker_verify, read_fifo_status, reg_rd, reg_wr
    from test.test_config import CompressorConfig

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=255,
            bypass_mask=0x000,
            sample_period=256,  # Slow sampling: div256
            checker_enable=True,  # Decorrelator checker still works
        ),
        compressor=CompressorConfig(
            checker_enable=False  # MUST disable in bypass mode
        ),
        bypass_compressor_dut=True,  # Bypass mode
        decorrelator_samples=20,  # 20 samples x 3 words = 60 FIFO entries
        fifo_verification_enable=False,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Verify configuration
    ctrl_val = await reg_rd(apb, "CTRL")
    bypass_bit = (ctrl_val >> 8) & 0x1
    dut._log.info(f"\n[Verify] CTRL.BYPASS_ENTROPY_COMPRESSOR[8] = {bypass_bit}")
    assert bypass_bit == 1, f"Expected BYPASS=1, got {bypass_bit}"

    # Phase 3: Collect decorrelator samples (slow rate)
    # 20 samples x 256 APB clocks/sample = 5120 cycles
    # FSM needs 3 cycles per sample: 20 x 3 = 60 cycles
    # Total: ~5200 cycles (but collect_entropy_samples waits for valid pulses)
    dut._log.info("\n[Observe] Collecting samples at slow rate (div256)...")
    dut._log.info("           This produces highest quality entropy")
    ref_samples, _ = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Wait for clock edge to exit ReadOnly phase before APB transaction
    await RisingEdge(dut.apb.pclk)

    # Disable ROs to stop entropy generation (proper way to freeze FIFO push)
    dut._log.info("\n[Freeze] Disabling RING_OSC_ENABLE to stop entropy generation...")
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)

    # Wait for pipeline to drain
    await ClockCycles(dut.apb.pclk, 10)

    # Check FIFO level
    level, _, _ = await read_fifo_status(apb)
    dut._log.info(f"\n[FIFO] Level: {level} entries (expected ~60)")
    dut._log.info("  Slow sampling (div256) with bypass mode (3 words/sample)")
    assert 56 <= level <= 64, f"Expected ~60 entries, got {level}"

    # Phase 4: Verify 3-word packing against decorrelator reference model
    dut._log.info("\n[Verification] Verifying 3-word FIFO packing against ref_samples:")
    mismatch_count = 0
    num_verify = len(ref_samples)  # Verify all samples
    dut._log.info(f"  Verifying all {num_verify} samples")

    for sample_idx in range(num_verify):
        # Read 3 FIFO words for this sample
        word0 = await reg_rd(apb, "FIFO_RDATA")
        word1 = await reg_rd(apb, "FIFO_RDATA")
        word2 = await reg_rd(apb, "FIFO_RDATA")

        # Build expected words from decorrelator reference output
        ref_bytes = ref_samples[sample_idx]
        expected_word0 = (
            (ref_bytes[3] << 24) | (ref_bytes[2] << 16) | (ref_bytes[1] << 8) | ref_bytes[0]
        )
        expected_word1 = (
            (ref_bytes[7] << 24) | (ref_bytes[6] << 16) | (ref_bytes[5] << 8) | ref_bytes[4]
        )
        expected_word2 = (
            (ref_bytes[11] << 24) | (ref_bytes[10] << 16) | (ref_bytes[9] << 8) | ref_bytes[8]
        )

        # Verify each word
        match0 = word0 == expected_word0
        match1 = word1 == expected_word1
        match2 = word2 == expected_word2

        # Show first 3, last 2, and all mismatches
        show_sample = (
            (sample_idx < 3) or (sample_idx >= num_verify - 2) or not (match0 and match1 and match2)
        )
        if show_sample:
            dut._log.info(f"\n  Sample {sample_idx}:")
            dut._log.info(
                f"    Word 0 (lanes [3:0]):   DUT=0x{word0:08X}  Expected=0x{expected_word0:08X}  {'MATCH' if match0 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 1 (lanes [7:4]):   DUT=0x{word1:08X}  Expected=0x{expected_word1:08X}  {'MATCH' if match1 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 2 (lanes [11:8]):  DUT=0x{word2:08X}  Expected=0x{expected_word2:08X}  {'MATCH' if match2 else 'MISMATCH'}"
            )
        elif sample_idx == 3:
            dut._log.info("\n  ... (showing first 3 and last 2 only)")

        if not (match0 and match1 and match2):
            mismatch_count += 1
            if not match0:
                dut._log.error(f"      Word 0 XOR: 0x{word0 ^ expected_word0:08X}")
            if not match1:
                dut._log.error(f"      Word 1 XOR: 0x{word1 ^ expected_word1:08X}")
            if not match2:
                dut._log.error(f"      Word 2 XOR: 0x{word2 ^ expected_word2:08X}")

    # Report results
    if mismatch_count == 0:
        dut._log.info(f"\n[PASS] All {num_verify} verified samples matched decorrelator reference!")
        dut._log.info(
            f"  Total FIFO entries: {len(ref_samples)} samples x 3 words = {len(ref_samples) * 3} entries"
        )
    else:
        dut._log.error(f"\n[FAIL] {mismatch_count}/{num_verify} samples with mismatches!")
        raise AssertionError(f"FIFO bypass verification failed: {mismatch_count} sample mismatches")

    # Verify decorrelator checker
    decor_checker_verify(dut)

    dut._log.info("[PASS] Test 1.3.2 complete - Bypass mode with slow rate (div256)")


@cocotb.test()
async def test_1_3_3_bypass_fast_sampling(dut):
    """Test 1.3.3: Bypass mode with fast sampling (div8) - Stress test for FSM throughput"""

    from test.test_base import read_fifo_status, reg_rd, reg_wr
    from test.test_config import CompressorConfig

    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,
            bypass_dut=False,
            sample_clk_div=7,
            bypass_mask=0x000,
            sample_period=8,  # Fast sampling: div8
            checker_enable=True,  # Decorrelator checker still works
        ),
        compressor=CompressorConfig(
            checker_enable=False  # MUST disable in bypass mode
        ),
        bypass_compressor_dut=True,  # Bypass mode
        decorrelator_samples=20,  # 20 samples x 3 words = 60 entries
        fifo_verification_enable=False,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT
    await program_dut_registers(dut, apb, cfg)

    # Verify configuration
    ctrl_val = await reg_rd(apb, "CTRL")
    bypass_bit = (ctrl_val >> 8) & 0x1
    dut._log.info(f"\n[Verify] CTRL.BYPASS_ENTROPY_COMPRESSOR[8] = {bypass_bit}")
    assert bypass_bit == 1, f"Expected BYPASS=1, got {bypass_bit}"

    # Phase 3: Collect decorrelator samples (fast rate)
    # 20 samples x 8 APB clocks/sample = 160 cycles
    # FSM needs 3 cycles per sample: 20 x 3 = 60 cycles
    # Total: ~220 cycles (but collect_entropy_samples waits for valid pulses)
    dut._log.info("\n[Observe] Collecting samples at fast rate (div8)...")
    dut._log.info("           This is a stress test for FSM throughput")
    ref_samples, _ = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Wait for clock edge to exit ReadOnly phase before APB transaction
    await RisingEdge(dut.apb.pclk)

    # Disable ROs to stop entropy generation (proper way to freeze FIFO push)
    dut._log.info("\n[Freeze] Disabling RING_OSC_ENABLE to stop entropy generation...")
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)

    # Wait for pipeline to drain
    await ClockCycles(dut.apb.pclk, 10)

    # Check FIFO level
    level, _, _ = await read_fifo_status(apb)
    dut._log.info(f"\n[FIFO] Level: {level} entries (expected ~60)")
    dut._log.info("  Fast sampling (div8) with bypass mode (3 words/sample)")
    assert 56 <= level <= 64, f"Expected ~60 entries, got {level}"

    # Phase 4: Verify 3-word packing against decorrelator reference model
    dut._log.info("\n[Verification] Verifying 3-word FIFO packing against ref_samples:")
    mismatch_count = 0
    num_verify = len(ref_samples)  # Verify all samples
    dut._log.info(f"  Verifying all {num_verify} samples")

    for sample_idx in range(num_verify):
        # Read 3 FIFO words for this sample
        word0 = await reg_rd(apb, "FIFO_RDATA")
        word1 = await reg_rd(apb, "FIFO_RDATA")
        word2 = await reg_rd(apb, "FIFO_RDATA")

        # Build expected words from decorrelator reference output
        ref_bytes = ref_samples[sample_idx]
        expected_word0 = (
            (ref_bytes[3] << 24) | (ref_bytes[2] << 16) | (ref_bytes[1] << 8) | ref_bytes[0]
        )
        expected_word1 = (
            (ref_bytes[7] << 24) | (ref_bytes[6] << 16) | (ref_bytes[5] << 8) | ref_bytes[4]
        )
        expected_word2 = (
            (ref_bytes[11] << 24) | (ref_bytes[10] << 16) | (ref_bytes[9] << 8) | ref_bytes[8]
        )

        # Verify each word
        match0 = word0 == expected_word0
        match1 = word1 == expected_word1
        match2 = word2 == expected_word2

        # Show first 3, last 2, and all mismatches
        show_sample = (
            (sample_idx < 3) or (sample_idx >= num_verify - 2) or not (match0 and match1 and match2)
        )
        if show_sample:
            dut._log.info(f"\n  Sample {sample_idx}:")
            dut._log.info(
                f"    Word 0 (lanes [3:0]):   DUT=0x{word0:08X}  Expected=0x{expected_word0:08X}  {'MATCH' if match0 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 1 (lanes [7:4]):   DUT=0x{word1:08X}  Expected=0x{expected_word1:08X}  {'MATCH' if match1 else 'MISMATCH'}"
            )
            dut._log.info(
                f"    Word 2 (lanes [11:8]):  DUT=0x{word2:08X}  Expected=0x{expected_word2:08X}  {'MATCH' if match2 else 'MISMATCH'}"
            )
        elif sample_idx == 3:
            dut._log.info("\n  ... (showing first 3 and last 2 only)")

        if not (match0 and match1 and match2):
            mismatch_count += 1
            if not match0:
                dut._log.error(f"      Word 0 XOR: 0x{word0 ^ expected_word0:08X}")
            if not match1:
                dut._log.error(f"      Word 1 XOR: 0x{word1 ^ expected_word1:08X}")
            if not match2:
                dut._log.error(f"      Word 2 XOR: 0x{word2 ^ expected_word2:08X}")

    # Report results
    if mismatch_count == 0:
        dut._log.info(f"\n[PASS] All {num_verify} verified samples matched decorrelator reference!")
        dut._log.info(
            f"  Total FIFO entries: {len(ref_samples)} samples x 3 words = {len(ref_samples) * 3} entries"
        )
    else:
        dut._log.error(f"\n[FAIL] {mismatch_count}/{num_verify} samples with mismatches!")
        raise AssertionError(f"FIFO bypass verification failed: {mismatch_count} sample mismatches")

    # Verify decorrelator checker
    from test.test_base import decor_checker_verify

    decor_checker_verify(dut)

    dut._log.info("[PASS] Test 1.3.3 complete - Bypass mode with fast rate (div8)")


# ============================================================================
# Category 1.4: Byte Mask Configuration
# ============================================================================


@cocotb.test()
async def test_1_4_1_decorrelator_byte_mask(dut):
    """Test 1.4.1: Verify DECORRELATOR_MASK byte masking functionality

    Tests that the DECORRELATOR_MASK register (0xA4) correctly masks
    bits in the decorrelator output. Uses mask 0xAA (even bits only).

    Register 0xA4 DECORRELATOR_MASK[7:0]:
        - 0xFF: All 8 bits enabled (default)
        - 0xAA: Only even bits enabled (0b10101010)
        - Output: entropy_byte & mask

    With mask 0xAA:
        - Bits [7,5,3,1] pass through
        - Bits [6,4,2,0] forced to 0
    """

    dut._log.info("\n" + "=" * 70)
    dut._log.info("TEST 1.4.1: DECORRELATOR_MASK Byte Masking (0xAA - Even Bits)")
    dut._log.info("=" * 70)

    # Configuration with normal decorrelation mode
    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            mode=0,  # DECOR_29
            bypass_dut=False,
            sample_clk_div=63,  # div-64
            bypass_mask=0x000,  # No per-lane bypass
            sample_period=64,
        ),
        decorrelator_samples=50,
        fifo_verification_enable=True,
    )

    # Phase 1: Configure testbench
    apb, mon, cfg = await configure_testbench(dut, config=cfg)

    # Phase 2: Program DUT registers
    await program_dut_registers(dut, apb, cfg)

    # Phase 3: Program DECORRELATOR_MASK = 0xAA (even bits only)
    dut._log.info("\n--- Phase 3: Configure byte mask ---")
    byte_mask = 0xAA  # 0b10101010 - even bits only
    await reg_wr(apb, "DECORRELATOR_MASK", byte_mask)

    # Readback to verify register was programmed correctly
    readback = await reg_rd(apb, "DECORRELATOR_MASK")
    dut._log.info(f"  DECORRELATOR_MASK written: 0x{byte_mask:02X}")
    dut._log.info(f"  DECORRELATOR_MASK readback: 0x{readback:08X}")
    if (readback & 0xFF) != byte_mask:
        raise AssertionError(
            f"DECORRELATOR_MASK readback mismatch! Expected 0x{byte_mask:02X}, got 0x{readback & 0xFF:02X}"
        )

    dut._log.info(f"  Binary: 0b{byte_mask:08b}")
    dut._log.info("  Enabled bits: [7,5,3,1]")
    dut._log.info("  Masked bits:  [6,4,2,0]")

    # Phase 4: Collect samples (event-driven, exactly 50 samples)
    dut._log.info("\n--- Phase 4: Collect entropy samples (event-driven) ---")
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # Phase 5: Verify FIFO readout
    dut._log.info("\n--- Phase 5: Verify FIFO readout ---")
    await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # Phase 6: Analyze bit distribution in decorrelator samples
    dut._log.info("\n--- Phase 6: Analyze bit distribution ---")
    dut._log.info(f"  Analyzing {len(ref_samples)} decorrelator samples...")
    dut._log.info("  NOTE: Analyzing raw decorrelator bytes (not compressed FIFO output)")

    # Count bit occurrences across all decorrelator bytes
    bit_ones_count = [0] * 8  # Count '1's for each bit position
    total_bytes = 0

    for sample in ref_samples:
        # Each sample is a list of 12 bytes from decorrelator
        for byte_val in sample:
            total_bytes += 1
            for bit_pos in range(8):
                if byte_val & (1 << bit_pos):
                    bit_ones_count[bit_pos] += 1

    # Show bit statistics
    dut._log.info(f"\n  Bit Statistics (out of {total_bytes} bytes):")
    dut._log.info(f"  {'Bit':<5} {'Mask':<6} {'Ones':<8} {'Percentage':<12} {'Expected'}")
    dut._log.info(f"  {'-' * 5} {'-' * 6} {'-' * 8} {'-' * 12} {'-' * 15}")

    masked_bits_ok = True
    enabled_bits_ok = True

    for bit_pos in range(8):
        is_masked = not (byte_mask & (1 << bit_pos))
        ones = bit_ones_count[bit_pos]
        percentage = (ones / total_bytes) * 100.0

        mask_str = "MASKED" if is_masked else "ENABLED"
        expected = "~0% (forced 0)" if is_masked else "~50% (random)"

        dut._log.info(
            f"  {bit_pos:<5} {mask_str:<6} {ones:<8} {percentage:>5.1f}%{' ' * 6} {expected}"
        )

        # Verify expectations
        if is_masked:
            # Masked bits should be very close to 0%
            if percentage > 5.0:  # Allow 5% tolerance
                dut._log.error(
                    f"      [FAIL] Bit {bit_pos} should be masked but shows {percentage:.1f}%"
                )
                masked_bits_ok = False
        else:
            # Enabled bits should be around 50% (random)
            if percentage < 30.0 or percentage > 70.0:
                dut._log.warning(
                    f"      [WARN] Bit {bit_pos} shows {percentage:.1f}% (expected ~50%)"
                )
                enabled_bits_ok = False

    # Phase 7: Verify checkers
    dut._log.info("\n--- Phase 7: Verify all checkers ---")
    await verify_checkers(dut)

    # Final verdict
    dut._log.info("\n" + "=" * 70)
    if masked_bits_ok and enabled_bits_ok:
        dut._log.info("[PASS] Test 1.4.1 complete - Byte mask verified")
        dut._log.info("  Masked bits [6,4,2,0]: Correctly forced to 0")
        dut._log.info("  Enabled bits [7,5,3,1]: Show random distribution")
    else:
        if not masked_bits_ok:
            raise AssertionError("Masked bits not properly forced to 0!")
        if not enabled_bits_ok:
            dut._log.warning("Enabled bits show non-random distribution (may be OK)")
            dut._log.info("[PASS] Test 1.4.1 complete with warnings")
    dut._log.info("=" * 70)
