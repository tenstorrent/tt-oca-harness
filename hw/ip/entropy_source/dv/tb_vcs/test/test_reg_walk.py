# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Register Walking Test for Entropy Source

Comprehensive test that walks through all registers in the entropy source:
1. Verify default values after reset on all readable registers
2. Test RW access on writable registers with multiple patterns
3. Minimal skips: only write-only (INTR_TEST) and special W1C (INTR_STATUS)

Based on entropy_source.rdl register definitions.
"""

import cocotb
from cocotb.triggers import ClockCycles

from test.test_base import *
from test.test_config import CompressorConfig, DecorrelatorConfig, ROConfig, get_custom_config


@cocotb.test()
async def test_reg_walk(dut):
    """
    Comprehensive register walking test.

    Tests performed:
    1. Check default values on all readable registers
    2. Write/read test on all RW registers with multiple patterns
    3. Minimal skips: only INTR_TEST (WO) in default check, INTR_STATUS/INTR_TEST in RW test

    Configuration:
    - APB Clock: 100 MHz, RO Sample Clock: 142.9 MHz
    - RO Model Injection: DISABLED (pure register testing)
    - All checkers: DISABLED (focus on register access only)
    - FIFO Error Monitor: DISABLED (register walk reads empty FIFO)
    """
    cfg = get_custom_config(
        ro=ROConfig(inject_model=0),  # Disable RO model injection
        decorrelator=DecorrelatorConfig(
            checker_enable=False  # Disable decorrelator checker
        ),
        compressor=CompressorConfig(
            enable=False,  # Disable compressor model
            checker_enable=False,  # Disable compressor checker
        ),
        fifo_error_monitor_enable=False,  # Disable FIFO error monitor (register walk reads empty FIFO)
    )

    dut._log.info("=" * 80)
    dut._log.info("ENTROPY SOURCE - REGISTER WALK TEST")
    dut._log.info("=" * 80)
    dut._log.info(
        f"Clock Config: APB {cfg.clock.apb_freq_mhz:.1f} MHz, RO {cfg.clock.rosc_freq_mhz:.1f} MHz"
    )
    dut._log.info("RO Model Injection: DISABLED (pure register testing)")
    dut._log.info("Decorrelator Checker: DISABLED")
    dut._log.info("Compressor Model: DISABLED")
    dut._log.info("Compressor Checker: DISABLED")
    dut._log.info("FIFO Error Monitor: DISABLED")
    dut._log.info("=" * 80)

    apb, mon = await init(dut, config=cfg)

    # ========================================================================
    # Apply hardware reset to get clean defaults
    # ========================================================================
    dut._log.info("\n[SETUP] Applying APB hardware reset for clean default values...")
    await apb_reset(apb)
    dut._log.info("  Hardware reset applied - all registers at default values")

    # ========================================================================
    # Define skip lists for different test phases
    # ========================================================================
    # Skip default value checks for write-only registers (cannot be read)
    skip_default_check = [
        "INTR_TEST",  # Write-only register (cannot read back)
    ]

    # Health test status registers that may increment during the test
    # These will be checked specially after disabling health tests
    health_status_regs = [
        "REPETITION_TEST_COUNT",
        "APT_PATTERN_COUNT_1BIT",
        "APT_PATTERN_COUNT_2BIT",
        "MARKOV_TEST_COUNTS_0",
    ]

    # Skip RW tests for special registers that need dedicated testing
    skip_rw_test = [
        "INTR_STATUS",  # Write-one-to-clear, needs special W1C testing
        "INTR_TEST",  # Write-only, cannot read back
    ]

    # ========================================================================
    # Part 1: Check default values on all readable registers
    # ========================================================================
    dut._log.info("\n[1/3] Checking default values after reset...")
    dut._log.info("-" * 80)

    default_pass = 0
    default_fail = 0
    default_skip = 0

    for reg_name, (addr, access, desc, expected_default, write_mask) in sorted(
        REG_MAP.items(), key=lambda x: x[1][0]
    ):
        # Skip registers in skip list
        if reg_name in skip_default_check:
            if reg_name == "INTR_TEST":
                reason = "Write-only register (cannot read back)"
            else:
                reason = "Special register"
            dut._log.info(f"  [SKIP] 0x{addr:02X} {reg_name:35s} - {reason}")
            default_skip += 1
            continue

        # Skip health status registers for now (will check after disabling health tests)
        if reg_name in health_status_regs:
            dut._log.info(
                f"  [DEFER] 0x{addr:02X} {reg_name:35s} - Will check after disabling health tests"
            )
            default_skip += 1
            continue

        # Only check readable registers
        if access in ["RO", "RW"]:
            try:
                value = await reg_rd(apb, reg_name)

                if value == expected_default:
                    dut._log.info(
                        f"  [PASS] 0x{addr:02X} {reg_name:35s} = 0x{value:08X} (expected 0x{expected_default:08X})"
                    )
                    default_pass += 1
                else:
                    dut._log.error(
                        f"  [FAIL] 0x{addr:02X} {reg_name:35s} = 0x{value:08X} (expected 0x{expected_default:08X})"
                    )
                    default_fail += 1
            except Exception as e:
                dut._log.error(f"  [ERROR] 0x{addr:02X} {reg_name:35s} - Read failed: {e}")
                default_fail += 1

    dut._log.info(
        f"\nDefault Value Check (Part 1): {default_pass} pass, {default_fail} fail, {default_skip} deferred/skipped"
    )

    # ========================================================================
    # Part 1.5: Disable health tests and check status register defaults
    # ========================================================================
    dut._log.info(
        "\n[1.5/3] Checking health status register defaults (after disabling health tests)..."
    )
    dut._log.info("-" * 80)
    dut._log.info("  Health tests enabled by default, so status counters may be non-zero.")
    dut._log.info("  Disabling health tests, then checking their cleared count state.")

    # Disabling each test clears its live count state.
    await reg_wr(apb, "HEALTH_TEST_CTRL", 0x00000000)
    await ClockCycles(dut.apb.pclk, 2)
    dut._log.info("  Health tests disabled")

    # Now check health status registers
    health_status_pass = 0
    health_status_fail = 0

    for reg_name in sorted(health_status_regs, key=lambda x: REG_MAP[x][0]):
        addr, access, desc, expected_default, write_mask = REG_MAP[reg_name]
        try:
            value = await reg_rd(apb, reg_name)

            if value == expected_default:
                dut._log.info(
                    f"  [PASS] 0x{addr:02X} {reg_name:35s} = 0x{value:08X} (expected 0x{expected_default:08X})"
                )
                health_status_pass += 1
            else:
                dut._log.error(
                    f"  [FAIL] 0x{addr:02X} {reg_name:35s} = 0x{value:08X} (expected 0x{expected_default:08X})"
                )
                health_status_fail += 1
        except Exception as e:
            dut._log.error(f"  [ERROR] 0x{addr:02X} {reg_name:35s} - Read failed: {e}")
            health_status_fail += 1

    # Update totals
    default_pass += health_status_pass
    default_fail += health_status_fail
    default_skip -= len(health_status_regs)  # They were deferred, not skipped

    dut._log.info(
        f"\nDefault Value Check (Complete): {default_pass} pass, {default_fail} fail, {default_skip} skipped"
    )

    # ========================================================================
    # Part 2: Write/read test on RW registers
    # ========================================================================
    dut._log.info("\n[2/3] Testing RW register access...")
    dut._log.info("-" * 80)

    # Test patterns: all-zeros, all-ones, checkerboard patterns
    test_patterns = [0x00000000, 0xFFFFFFFF, 0x5555AAAA, 0xAAAA5555]

    rw_pass = 0
    rw_fail = 0
    rw_skip = 0

    # Get RW registers only
    rw_regs = {name: reg_info for name, reg_info in REG_MAP.items() if reg_info[1] == "RW"}

    for reg_name, (addr, access, desc, expected_default, write_mask) in sorted(
        rw_regs.items(), key=lambda x: x[1][0]
    ):
        # Skip registers in skip list
        if reg_name in skip_rw_test:
            dut._log.info(f"  [SKIP] 0x{addr:02X} {reg_name:35s} - Special register (W1C/WO)")
            rw_skip += 1
            continue

        dut._log.info(f"\n  Testing {reg_name} @ 0x{addr:02X} (write_mask: 0x{write_mask:08X})")

        pattern_pass = 0
        pattern_fail = 0

        for pattern in test_patterns:
            try:
                # Write pattern
                await reg_wr(apb, reg_name, pattern)

                # Read back
                readback = await reg_rd(apb, reg_name)

                # Apply write mask to both values before comparison
                # Only writable bits should match the pattern
                expected_masked = pattern & write_mask
                readback_masked = readback & write_mask

                if readback_masked == expected_masked:
                    dut._log.info(
                        f"    [PASS] Write 0x{pattern:08X} -> Read 0x{readback:08X} (masked: 0x{readback_masked:08X})"
                    )
                    pattern_pass += 1
                else:
                    # Calculate which writable bits differ
                    diff_bits = expected_masked ^ readback_masked
                    dut._log.error(f"    [FAIL] Write 0x{pattern:08X} -> Read 0x{readback:08X}")
                    dut._log.error(
                        f"           Expected (masked): 0x{expected_masked:08X}, Got (masked): 0x{readback_masked:08X}"
                    )
                    dut._log.error(f"           Writable bits differ: 0x{diff_bits:08X}")
                    pattern_fail += 1

            except Exception as e:
                dut._log.error(f"    [ERROR] Pattern 0x{pattern:08X} failed: {e}")
                pattern_fail += 1

        # Restore default value
        try:
            await reg_wr(apb, reg_name, expected_default)
            dut._log.info(f"  [RESTORE] {reg_name} restored to default 0x{expected_default:08X}")
        except Exception as e:
            dut._log.error(f"  [ERROR] Failed to restore {reg_name} to default: {e}")

        if pattern_fail == 0:
            dut._log.info(f"  [PASS] {reg_name}: All patterns passed")
            rw_pass += 1
        else:
            dut._log.error(
                f"  [FAIL] {reg_name}: {pattern_fail}/{len(test_patterns)} patterns had differences"
            )
            rw_fail += 1

    dut._log.info(f"\nRW Access Test: {rw_pass} pass, {rw_fail} fail, {rw_skip} skipped")

    # ========================================================================
    # Part 3: Register map summary
    # ========================================================================
    dut._log.info("\n[3/3] Register Map Statistics")
    dut._log.info("-" * 80)
    dut._log.info(f"  Total Registers: {len(REG_MAP)}")
    dut._log.info(f"  Skipped in Default Check: {len(skip_default_check)}")
    dut._log.info(f"  Skipped in RW Test: {len(skip_rw_test)}")

    # Count by access type
    access_counts = {}
    for name, (addr, access, desc, default, write_mask) in REG_MAP.items():
        access_counts[access] = access_counts.get(access, 0) + 1

    for access_type, count in sorted(access_counts.items()):
        dut._log.info(f"    {access_type}: {count} registers")

    dut._log.info(
        f"\n  Address Range: 0x{min(addr for _, (addr, _, _, _, _) in REG_MAP.items()):02X} - "
        f"0x{max(addr for _, (addr, _, _, _, _) in REG_MAP.items()):02X}"
    )

    # ========================================================================
    # Final summary
    # ========================================================================
    total_failures = default_fail + rw_fail

    dut._log.info("\n" + "=" * 80)
    dut._log.info("TEST RESULTS")
    dut._log.info("=" * 80)
    dut._log.info(
        f"  Default Value Checks:  {default_pass} pass, {default_fail} fail, {default_skip} skipped"
    )
    dut._log.info(f"  RW Access Tests:       {rw_pass} pass, {rw_fail} fail, {rw_skip} skipped")
    dut._log.info(f"  Total Failures:        {total_failures}")

    if total_failures == 0:
        dut._log.info("\n  [PASS] All register checks completed successfully!")
    else:
        dut._log.error(f"\n  [FAIL] {total_failures} errors detected during register walk")
        raise AssertionError(f"Register walk failed with {total_failures} errors")

    dut._log.info("=" * 80)
