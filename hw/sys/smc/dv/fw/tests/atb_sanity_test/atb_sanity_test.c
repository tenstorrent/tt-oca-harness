/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief Telemetry Sanity Basic Test - Register Reset Values
 *
 * Verifies that firmware can read the registers of Telemetry Receiver
 * instance 0 and that the fields it checks hold their generated reset
 * values.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"

/* Fail the test when a register field differs from its generated reset value. */
static void expect_field(const char *name, uint32_t got, uint32_t bm, uint32_t bp, uint32_t want) {
    uint32_t val = (got & bm) >> bp;
    simputs("  ");
    simputs(name);
    simputshex32(" = ", val);
    if (val != want) {
        simputshex32("  MISMATCH: expected ", want);
        simputs("\n");
        write_scratch(0, 0xBAD00010u);
        test_fail(0);
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

    test_step = 1;
    write_scratch(1, test_step);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");

    test_step = 2;
    write_scratch(1, test_step);
    simputs("Step 2: Read CTRL register\n");
    uint32_t ctrl_val =
        read_reg(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR(0));
    expect_field("CTRL.BUFFER_THRESHOLD", ctrl_val, TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm,
                 TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp,
                 TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_reset);

    test_step = 3;
    write_scratch(1, test_step);
    simputs("Step 3: Read STATUS register\n");
    uint32_t status_val =
        read_reg(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR(0));
    expect_field("STATUS.BUFFER_EMPTY", status_val, TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm,
                 TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bp,
                 TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_reset);

    test_step = 4;
    write_scratch(1, test_step);
    simputs("Step 4: Read TELEMETRY_DATA register on the empty buffer\n");
    uint32_t data_val = read_reg(
        SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_DATA_BASE_ADDR(0));
    expect_field("TELEMETRY_DATA.DATA", data_val, TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__DATA_reset);
    expect_field("TELEMETRY_DATA.ATID", data_val, TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__ATID_reset);
    expect_field("TELEMETRY_DATA.VALID", data_val, TELEMETRY_RECEIVER__TELEMETRY_DATA__VALID_bm,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__VALID_bp,
                 TELEMETRY_RECEIVER__TELEMETRY_DATA__VALID_reset);

    test_step = 5;
    write_scratch(1, test_step);
    simputs("Step 5: Test Complete\n");
    simputs("  ========================================\n");
    simputs("  All telemetry registers accessible\n");
    simputs("  CTRL:                  0x");
    simputshex32("", ctrl_val);
    simputs("\n");
    simputs("  STATUS:                0x");
    simputshex32("", status_val);
    simputs("\n");
    simputs("  TELEMETRY_DATA:        0x");
    simputshex32("", data_val);
    simputs("\n");
    simputs("  ========================================\n");

    // Signal test completion
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);
}
