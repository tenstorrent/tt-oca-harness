/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief Telemetry Sanity Basic Test - Register Read/Write Verification
 *
 * This test performs basic register read/write operations on Telemetry
 * Receiver registers to ensure the IP is accessible and functioning correctly.
 *
 * Test Flow:
 * 1. System initialization
 * 2. Read Telemetry CTRL register
 * 3. Read Telemetry STATUS register
 * 4. Read Telemetry PROBE_ID register
 * 5. Read Telemetry COUNTER_VLDS register
 * 6. Read telemetry counter values
 *
 * =============================================================================
 * Telemetry Receiver Register Map (Receiver 0)
 * =============================================================================
 *
 * Offset  | Register Name           | Purpose
 * --------|-------------------------|--------------------------------------------------
 * 0x0000  | CTRL                    | Control register
 * 0x0004  | STATUS                  | Status register
 * 0x0008  | INTR_STATUS             | Interrupt status
 * 0x000C  | INTR_ENABLE             | Interrupt enable
 * 0x0010  | INTR_TEST               | Interrupt test
 * 0x0014  | TELEMETRY_PROBE_ID      | Probe identifier
 * 0x0018  | TELEMETRY_COUNTER_VLDS  | Counter valid bits (32-bit mask)
 * 0x0080+ | TELEMETRY_COUNTER[0-31] | Counter values (32 counters, each 4 bytes)
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"

/* Compare a register read against the generated reset default and fail on
 * mismatch. Expectations come from the generated reset constants in
 * smc_top_regs.h, reached through smc_io.h, so the golden is the generated map.
 */
static void expect_field(const char *name, uint32_t got, uint32_t bm, uint32_t bp, uint32_t want) {
    uint32_t val = (got & bm) >> bp;
    simputs("  ");
    simputs(name);
    simputshex32(" = ", val);
    if (val != want) {
        simputshex32("  MISMATCH: expected ", want);
        simputs("\n");
        write_scratch(0, 0xBAD00010u);
        test_fail(0); /* noreturn */
    }
    simputshex32("  == generated reset ", want);
    simputs("\n");
}

int main(void) {
    uint32_t test_step = 0;

    simputs("\n");
    simputs("################################################\n");
    simputs("##  Telemetry Sanity Basic Test               ##\n");
    simputs("################################################\n");
    simputs("\n");

    // Step 1: System initialization complete
    test_step = 1;
    write_scratch(1, test_step);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");

    // Step 2: Read CTRL register to verify telemetry is accessible
    test_step = 2;
    write_scratch(1, test_step);
    simputs("Step 2: Read CTRL register\n");
    uint32_t ctrl_val =
        read_reg(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR(0));
    expect_field("CTRL.BUFFER_THRESHOLD", ctrl_val, TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm,
                 TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp,
                 TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_reset);

    // Step 3: Read STATUS register
    test_step = 3;
    write_scratch(1, test_step);
    simputs("Step 3: Read STATUS register\n");
    uint32_t status_val =
        read_reg(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR(0));
    expect_field("STATUS.BUFFER_EMPTY", status_val, TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm,
                 TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bp,
                 TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_reset);

    // Step 4: Read TELEMETRY_PROBE_ID register
    test_step = 4;
    write_scratch(1, test_step);
    simputs("Step 4: Read TELEMETRY_PROBE_ID register\n");
    uint32_t probe_id_val = read_reg(
        SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_PROBE_ID_BASE_ADDR(0));
    expect_field("TELEMETRY_PROBE_ID.PROBE_ID", probe_id_val,
                 TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_reset);

    // Step 5: Read TELEMETRY_COUNTER_VLDS register
    test_step = 5;
    write_scratch(1, test_step);
    simputs("Step 5: Read TELEMETRY_COUNTER_VLDS register\n");
    uint32_t counter_vlds_val = read_reg(
        SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_VLDS_BASE_ADDR(0));
    expect_field("TELEMETRY_COUNTER_VLDS.COUNTER_VLDS", counter_vlds_val,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_reset);

    // Step 6: Read telemetry counter values
    test_step = 6;
    write_scratch(1, test_step);
    simputs("Step 6: Read telemetry counter values\n");
    simputs("  Reading first 6 counter registers...\n");
    for (int i = 0; i < 6; i++) {
        uint32_t counter_addr =
            SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR(0,
                                                                                               i);
        uint32_t counter_val = read_reg(counter_addr);
        simputs("  TELEMETRY_COUNTER[");
        simputshex32("", i);
        simputs("] @ ");
        simputshex32("", counter_addr);
        expect_field("TELEMETRY_COUNTER.COUNTER", counter_val,
                     TELEMETRY_RECEIVER__TELEMETRY_COUNTER__COUNTER_bm,
                     TELEMETRY_RECEIVER__TELEMETRY_COUNTER__COUNTER_bp,
                     TELEMETRY_RECEIVER__TELEMETRY_COUNTER__COUNTER_reset);
    }

    // Step 7: Test complete - all register reads done
    test_step = 7;
    write_scratch(1, test_step);
    simputs("Step 7: Test Complete\n");
    simputs("  ========================================\n");
    simputs("  All telemetry registers accessible\n");
    simputs("  CTRL:                  0x");
    simputshex32("", ctrl_val);
    simputs("\n");
    simputs("  STATUS:                0x");
    simputshex32("", status_val);
    simputs("\n");
    simputs("  TELEMETRY_PROBE_ID:    0x");
    simputshex32("", probe_id_val);
    simputs("\n");
    expect_field("TELEMETRY_COUNTER_VLDS.COUNTER_VLDS", counter_vlds_val,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_COUNTER_VLDS__COUNTER_VLDS_reset);
    simputs("  ========================================\n");

    // Signal test completion
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return 0;
}
