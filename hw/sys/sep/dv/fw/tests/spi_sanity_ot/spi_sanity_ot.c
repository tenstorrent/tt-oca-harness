/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI Sanity Test for OCAH SEP - OpenTitan SPI Host
 *
 * CSR smoke: check POR defaults and simple write/readback on INTR_ENABLE,
 * INTR_TEST, CTRL, CFG, CSID, and EVENT_ENABLE.
 *
 * Test Flow:
 *   1. Verify SPI controller CSR defaults and write/readback
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("OCAH SEP OpenTitan SPI Host Sanity Test\n");
    printf("========================================\n");
    printf("\nCSR smoke: SPI controller POR/R/W\n\n");

    printf("SPI Control Base: 0x%08x\n", OCH_SEP_TOP_SPI_CONTROLLER_BASE_ADDR);

    int pass = 1;

    printf("\n--- Testing SPI Controller Registers ---\n\n");

    uint32_t read_val, expected_val, write_val;

    // Test 1: INTR_ENABLE - POR from generated field resets
    printf("Test 1: INTR_ENABLE\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    expected_val = OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, ERROR) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_ENABLE, SPI_EVENT);
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = SPI_CONTROLLER__INTR_ENABLE__ERROR_bm | SPI_CONTROLLER__INTR_ENABLE__SPI_EVENT_bm;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR);
    printf("  Write 0x%08x, readback 0x%08x - %s\n", write_val, read_val,
           (read_val == write_val) ? "PASS" : "FAIL");
    if (read_val != write_val) pass = 0;

    // Test 2: INTR_TEST - POR from generated field resets
    printf("\nTest 2: INTR_TEST\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR);
    expected_val = OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, ERROR) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__INTR_TEST, SPI_EVENT);
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = SPI_CONTROLLER__INTR_TEST__ERROR_bm | SPI_CONTROLLER__INTR_TEST__SPI_EVENT_bm;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_INTR_TEST_BASE_ADDR);
    printf("  Write 0x%08x, readback 0x%08x - %s\n", write_val, read_val,
           (read_val == write_val) ? "PASS" : "FAIL");
    if (read_val != write_val) pass = 0;

    // Test 3: CTRL - POR from generated aggregate
    printf("\nTest 3: CTRL\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    expected_val = SPI_CONTROLLER__CTRL_reset;
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = 0xA0001234; // Set SPIEN, OUTPUT_EN, and watermarks
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    // Mask out SW_RST bit which is write-only singlepulse
    expected_val = write_val & ~SPI_CONTROLLER__CTRL__SW_RST_bm;
    printf("  Write 0x%08x, readback 0x%08x (expected 0x%08x) - %s\n", write_val, read_val,
           expected_val, (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    // Test 4: CFG - POR from generated aggregate
    printf("\nTest 4: CFG\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR);
    expected_val = SPI_CONTROLLER__CFG_reset;
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = 0xCF0F5678; // Set CPOL, CPHA, FULLCYC, timing fields, CLKDIV
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR);
    printf("  Write 0x%08x, readback 0x%08x - %s\n", write_val, read_val,
           (read_val == write_val) ? "PASS" : "FAIL");
    if (read_val != write_val) pass = 0;

    // Test 5: CSID - POR from generated field reset
    printf("\nTest 5: CSID\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    expected_val = OCH_SEP_FIELD_RESET(SPI_CONTROLLER__CSID, CSID);
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = 0x00000003;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    printf("  Write 0x%08x, readback 0x%08x - %s\n", write_val, read_val,
           (read_val == write_val) ? "PASS" : "FAIL");
    if (read_val != write_val) pass = 0;

    // Test 6: EVENT_ENABLE - POR from generated field resets
    printf("\nTest 6: EVENT_ENABLE\n");
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    expected_val = OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXFULL) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXEMPTY) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, RXWM) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, TXWM) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, READY) |
                   OCH_SEP_FIELD_RESET(SPI_CONTROLLER__EVENT_ENABLE, IDLE);
    printf("  Read default: 0x%08x (expected 0x%08x) - %s\n", read_val, expected_val,
           (read_val == expected_val) ? "PASS" : "FAIL");
    if (read_val != expected_val) pass = 0;

    write_val = SPI_CONTROLLER__EVENT_ENABLE__RXFULL_bm | SPI_CONTROLLER__EVENT_ENABLE__TXEMPTY_bm |
                SPI_CONTROLLER__EVENT_ENABLE__RXWM_bm | SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm |
                SPI_CONTROLLER__EVENT_ENABLE__READY_bm | SPI_CONTROLLER__EVENT_ENABLE__IDLE_bm;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, write_val);
    read_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    printf("  Write 0x%08x, readback 0x%08x - %s\n", write_val, read_val,
           (read_val == write_val) ? "PASS" : "FAIL");
    if (read_val != write_val) pass = 0;

    // Final result
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI SANITY TEST PASSED ===\n");
        test_pass(0); // Signal testbench: TEST_PASSED
    } else {
        printf("=== SPI SANITY TEST FAILED ===\n");
        test_fail(0); // Signal testbench: TEST_FAILED
    }
    printf("========================================\n");

    // Keep CPU alive after signaling completion
    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
