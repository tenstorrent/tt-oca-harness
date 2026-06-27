# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

"""
Entropy Sanity Test - First Comprehensive End-to-End Test

This test validates the complete data flow:
1. RO model injection into DUT decorrelators
2. Decorrelator output validation against reference model (real-time checker)
3. Compressor output validation against reference model (real-time checker)
4. FIFO storage and readout verification (golden queue comparison)
5. Entropy data availability via APB interface

Test Plan: See TEST_ENTROPY_SANITY.md for detailed step-by-step flow
"""

import cocotb
from test.test_base import *
from test.test_config import get_custom_config, DecorrelatorConfig


@cocotb.test()
async def test_entropy_sanity(dut):
    """
    Entropy source sanity test - Complete end-to-end verification.

    Test flow:
      Phase 1: Testbench Configuration
      Phase 2: DUT Programming (APB)
      Phase 3: Sample Collection
      Phase 4: FIFO Readout Verification (optional)
      Phase 5: Checker Verification

    Configuration: test_config.py (single source of truth)
    """

    # ========================================================================
    # TEST CONFIGURATION
    # ========================================================================
    # Override decorrelator settings for this test
    # All other settings use defaults from test_config.py
    cfg = get_custom_config(
        decorrelator=DecorrelatorConfig(
            bypass_mask=0x0        # All lanes decorrelate (no bypass)
        ),
        decorrelator_samples=50,   # Collect 50 samples
        fifo_verification_enable=True  # Enable FIFO readout verification
    )

    # ========================================================================
    # PHASE 1: TESTBENCH CONFIGURATION
    # ========================================================================
    apb, mon, cfg = await configure_testbench(dut, cfg)

    # ========================================================================
    # PHASE 2: DUT PROGRAMMING (APB REGISTER ACCESS)
    # ========================================================================
    await program_dut_registers(dut, apb, cfg)

    # ========================================================================
    # PHASE 3: SAMPLE COLLECTION
    # ========================================================================
    ref_samples, golden_queue = await collect_entropy_samples(dut, cfg, cfg.decorrelator_samples)

    # ========================================================================
    # PHASE 4: FIFO READOUT VERIFICATION (Optional)
    # ========================================================================
    if cfg.fifo_verification_enable:
        await verify_fifo_readout(dut, apb, golden_queue, cfg.decorrelator_samples)

    # ========================================================================
    # PHASE 5: CHECKER VERIFICATION
    # ========================================================================
    await verify_checkers(dut)

    # ========================================================================
    # TEST SUMMARY
    # ========================================================================
    print_test_summary(dut, cfg, ref_samples, golden_queue)
