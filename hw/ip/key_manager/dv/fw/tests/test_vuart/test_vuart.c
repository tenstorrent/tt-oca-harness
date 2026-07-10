/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_vuart.c
 * @brief Virtual UART send/receive and printf functionality test
 *
 * Verifies the virtual UART interface works correctly by:
 * - Testing direct character send/receive via vuart_putc()/vuart_getc()
 * - Testing printf formatting functionality
 * - Verifying testbench actually received characters via TB_CMD_VUART_VERIFY
 * - Always enables VUART printing (this test must verify UART functionality)
 *
 * Run with:
 *   make run_fw FW_TEST=test_vuart
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Test values */
#define TEST_INT_VAL 12345
#define TEST_HEX_VAL 0xDEADBEEF
#define TEST_STRING "Hello"

/* SRAM location for storing expected strings for verification */
#define VUART_TEST_STR_ADDR (SRAM_BASE + 0x100) /* Offset 0x100 in SRAM */

/**
 * Verify VUART output by writing expected string to SRAM and requesting testbench verification.
 * This function handles the complete verification sequence:
 * 1. Write expected string to SRAM
 * 2. Memory barrier to ensure writes complete
 * 3. Wait for characters to be captured by testbench
 * 4. Request testbench verification via TB_CMD_VUART_VERIFY
 *
 * @param expected_string Null-terminated string that should have been sent via VUART
 * @return 1 if verification passed, 0 if failed
 */
static int vuart_verify_output(const char *expected_string) {
    volatile char *byte_addr = (volatile char *)VUART_TEST_STR_ADDR;

    /* Write expected string to SRAM byte by byte */
    int i = 0;
    while (expected_string[i] != '\0') {
        byte_addr[i] = expected_string[i];
        i++;
    }
    byte_addr[i] = '\0'; /* Null terminator */

    /* Memory barrier: ensure all writes complete */
    __asm__ volatile("fence" ::: "memory");

    /* Verify testbench received the characters */
    return tb_vuart_verify(VUART_TEST_STR_ADDR, 1000) == 1;
}

int main(void) {
    TEST_INIT();

    /* Test 1: Direct character transmission via vuart_putc() and verify reception */
    TEST_SUBTEST_START("Direct vuart_putc() with verification");
    /* Send characters */
    vuart_putc('H');
    vuart_putc('e');
    vuart_putc('l');
    vuart_putc('l');
    vuart_putc('o');
    vuart_putc('\n');

    /* Verify testbench received the characters */
    TEST_ASSERT(vuart_verify_output("Hello\n") == 1,
                "VUART verification failed - testbench did not receive characters");
    TEST_SUBTEST_PASS();

    /* Test 2: Verify TX_READY status bit */
    TEST_SUBTEST_START("TX_READY status");
    TEST_ASSERT(vuart_tx_ready() == 1, "TX should always be ready");
    TEST_SUBTEST_PASS();

    /* Test 3: Verify PRINT_ENABLE bit is set */
    TEST_SUBTEST_START("PRINT_ENABLE status");
    TEST_ASSERT(vuart_print_enabled() == 1, "PRINT_ENABLE should be set");
    TEST_SUBTEST_PASS();

    /* Test 4: String formatting via printf and verify reception */
    TEST_SUBTEST_START("String formatting with verification");
    printf("Test string: %s\n", TEST_STRING);
    TEST_ASSERT(vuart_verify_output("Test string: Hello\n") == 1,
                "VUART verification failed for printf");
    TEST_SUBTEST_PASS();

    /* Test 5: Integer formatting */
    TEST_SUBTEST_START("Integer formatting");
    printf("Test integer: %d\n", TEST_INT_VAL);
    TEST_ASSERT(vuart_verify_output("Test integer: 12345\n") == 1,
                "VUART verification failed for integer");
    printf("Negative: %d\n", -42);
    TEST_ASSERT(vuart_verify_output("Negative: -42\n") == 1,
                "VUART verification failed for negative integer");
    TEST_SUBTEST_PASS();

    /* Test 6: Hexadecimal formatting */
    TEST_SUBTEST_START("Hex formatting");
    printf("Test hex: 0x%8X\n", TEST_HEX_VAL);
    TEST_ASSERT(vuart_verify_output("Test hex: 0xDEADBEEF\n") == 1,
                "VUART verification failed for hex");
    TEST_SUBTEST_PASS();

    /* Test 7: Multiple values in one line */
    TEST_SUBTEST_START("Multiple values");
    printf("Values: int=%d hex=0x%X str=%s\n", 100, 0xFF, "OK");
    TEST_ASSERT(vuart_verify_output("Values: int=100 hex=0xFF str=OK\n") == 1,
                "VUART verification failed for multiple values");
    TEST_SUBTEST_PASS();

    /* Test 8: Character output */
    TEST_SUBTEST_START("Character output");
    printf("Char test: '%c'\n", 'A');
    TEST_ASSERT(vuart_verify_output("Char test: 'A'\n") == 1,
                "VUART verification failed for character");
    TEST_SUBTEST_PASS();

    /* Test 9: Percent sign */
    TEST_SUBTEST_START("Percent sign");
    printf("Percent: 100%%\n");
    TEST_ASSERT(vuart_verify_output("Percent: 100%\n") == 1,
                "VUART verification failed for percent sign");
    TEST_SUBTEST_PASS();

    /* Test 10: puts() function */
    TEST_SUBTEST_START("puts() function");
    puts("This is puts()");
    TEST_ASSERT(vuart_verify_output("This is puts()\n") == 1,
                "VUART verification failed for puts()");
    TEST_SUBTEST_PASS();

    /* Test 11: Direct putchar */
    TEST_SUBTEST_START("putchar() function");
    putchar('X');
    putchar('Y');
    putchar('Z');
    putchar('\n');
    TEST_ASSERT(vuart_verify_output("XYZ\n") == 1, "VUART verification failed for putchar()");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
