/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_soft_reset.c
 * @brief Test software-triggered soft reset via KMCSR SOFT_RST_CODE register
 *
 * This test exercises the soft reset functionality:
 * - Write correct code (0x53525354 = "SRST") to SOFT_RST_CODE register
 * - Verify that KM resets and restarts
 * - Testbench verifies restart by monitoring reset signal and test protocol registers
 *
 * Test flow:
 * 1. First execution: Write marker to SRAM, write signature, trigger soft reset
 * 2. After reset: Firmware restarts, checks marker, writes success signature
 * 3. Testbench monitors reset signal and verifies restart via test protocol registers
 *
 * The testbench should:
 * - Detect when soft reset is triggered (reset signal goes low)
 * - Wait for reset to de-assert
 * - Verify firmware restarts by checking test protocol registers are reset then updated
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Soft reset code: "SRST" = 0x53525354 */
#define SOFT_RST_CODE_MAGIC 0x53525354

/* Marker value written to a retained mid-SRAM location before reset. */
/* Keep this outside the startup-cleared globals for the current linker layout. */
#define RESET_MARKER_VALUE 0xDEADBEEF
#define RESET_MARKER_ADDR (SRAM_BASE + 0x3000)

/* Signatures to track execution phases */
#define SIGNATURE_BEFORE_RESET 0xABADCAFE /* "ABADCAFE" = about to reset */
#define SIGNATURE_AFTER_RESET 0xCAFEBABE  /* "CAFEBABE" = reset complete */

/* Register access macros - using generated header definitions */
#define KMCSR_SOFT_RST_CODE_REG (*(volatile uint32_t *)KEY_MANAGER_KMCSR_SOFT_RST_CODE_BASE_ADDR)

int main(void) {
    TEST_INIT();

    /* Check if this is the first run (before reset) or second run (after reset) */
    volatile uint32_t *marker = (volatile uint32_t *)RESET_MARKER_ADDR;

    if (*marker != RESET_MARKER_VALUE) {
        /* First execution: before reset */
        TEST_SUBTEST_START("Trigger soft reset");

        /* Write marker to SRAM - this should persist across reset */
        *marker = RESET_MARKER_VALUE;

        /* Verify write succeeded */
        if (*marker != RESET_MARKER_VALUE) {
            TEST_FAIL("SRAM marker write failed");
            return 1;
        }

        /* Write signature to indicate we're about to trigger reset */
        TEST_SIGNATURE = SIGNATURE_BEFORE_RESET;
        TEST_RESULT = 1;

        /* Write soft reset code to trigger reset */
        /* This should cause the KM to reset immediately */
        KMCSR_SOFT_RST_CODE_REG = SOFT_RST_CODE_MAGIC;

        /* Code should never reach here - reset should occur */
        /* If we reach here, soft reset didn't work */
        TEST_FAIL("Soft reset did not occur - execution continued after writing reset code");
        return 1;
    } else {
        /* Second execution: after reset */
        TEST_SUBTEST_START("Verify reset occurred and marker persisted");

        /* Verify marker is still present (confirms we restarted, not first run) */
        if (*marker == RESET_MARKER_VALUE) {
            /* Success: We restarted after soft reset and marker persisted */
            TEST_SIGNATURE = SIGNATURE_AFTER_RESET;
            TEST_RESULT = 1;
            TEST_SUBTEST_PASS();
            TEST_PASS();
            return 0;
        } else {
            /* Marker was lost - unexpected */
            TEST_FAIL("Reset marker lost after soft reset");
            return 1;
        }
    }
}
