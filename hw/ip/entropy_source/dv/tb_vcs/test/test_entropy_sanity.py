# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Entropy Sanity Test - Comprehensive End-to-End Test

This test validates the complete data flow:
1. RO model injection into DUT decorrelators
2. Decorrelator output validation against reference model (real-time checker)
3. Compressor output validation against reference model (real-time checker)
4. FIFO storage and readout verification (golden queue comparison)
5. Entropy data availability via APB interface
"""

import cocotb
from cocotb.handle import Force, Release
from cocotb.triggers import ReadOnly, RisingEdge

from test.test_base import *
from test.test_config import (
    CompressorConfig,
    DecorrelatorConfig,
    ROConfig,
    get_custom_config,
)


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
            bypass_mask=0x0  # All lanes decorrelate (no bypass)
        ),
        decorrelator_samples=50,  # Collect 50 samples
        fifo_verification_enable=True,  # Enable FIFO readout verification
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


@cocotb.test()
async def test_sha256_words_remaining_8_to_0(dut):
    """A completed digest reports eight words, then every accepted word decrements to idle zero."""
    cfg = get_custom_config(
        ro=ROConfig(inject_model=1, auto_randomize=True),
        decorrelator=DecorrelatorConfig(checker_enable=False),
        compressor=CompressorConfig(checker_enable=False),
        fifo_verification_enable=False,
    )
    apb, mon = await init(dut, config=cfg)

    idle_status = await reg_rd(apb, "SHA256_STATUS")
    assert ((idle_status >> 8) & 0xF) == 0, (
        f"SHA256_STATUS.OUTPUT_COUNT must be 0 while idle, got 0x{idle_status:08x}"
    )
    assert (idle_status & 0x1) == 0, (
        f"SHA256_STATUS.BUSY must be 0 while idle, got 0x{idle_status:08x}"
    )

    await enable_entropy_pipeline(apb, decorr_div=8)
    await reg_wr(apb, "CTRL", (1 << 28) | (1 << 1))

    whitener = dut.dut.u_sha256_whitener
    ready = whitener.whitened_ready_i
    ready.value = Force(0)
    observed = []
    try:
        for _ in range(20000):
            await RisingEdge(dut.apb.pclk)
            await ReadOnly()
            if int(whitener.output_count_o.value) == 8:
                break
        else:
            raise AssertionError("SHA-256 OUTPUT_COUNT never reached 8")

        for expected_count in range(8, 0, -1):
            status = await reg_rd(apb, "SHA256_STATUS")
            csr_count = (status >> 8) & 0xF
            rtl_count = int(whitener.output_count_o.value)
            busy = status & 0x1
            assert csr_count == expected_count, (
                f"APB OUTPUT_COUNT={csr_count}, expected {expected_count}; "
                f"SHA256_STATUS=0x{status:08x}"
            )
            assert rtl_count == expected_count, (
                f"RTL OUTPUT_COUNT={rtl_count}, expected {expected_count}"
            )
            assert csr_count == rtl_count, (
                f"APB OUTPUT_COUNT={csr_count} disagrees with RTL count={rtl_count}"
            )
            assert busy == 1, (
                f"SHA256_STATUS.BUSY must be 1 with {expected_count} word(s) remaining"
            )
            observed.append(csr_count)

            ready.value = Release()
            await RisingEdge(dut.apb.pclk)
            ready.value = Force(0)

        done_status = await reg_rd(apb, "SHA256_STATUS")
        done_csr_count = (done_status >> 8) & 0xF
        done_rtl_count = int(whitener.output_count_o.value)
        assert done_csr_count == 0 and done_rtl_count == 0, (
            f"OUTPUT_COUNT must return to 0 after the digest: "
            f"CSR={done_csr_count}, RTL={done_rtl_count}"
        )
        assert (done_status & 0x1) == 0, (
            f"SHA256_STATUS.BUSY must clear after the final word, got 0x{done_status:08x}"
        )
        observed.append(done_csr_count)
    finally:
        ready.value = Release()

    expected = list(range(8, -1, -1))
    assert observed == expected, (
        f"SHA-256 words-remaining sequence was {observed}, expected {expected}"
    )
    dut._log.info(
        "CHK-ENTROPY-SHA256-OUTPUT-COUNT: APB and RTL observed words remaining %s; "
        "BUSY stayed set through count 1 and cleared at done",
        observed,
    )
