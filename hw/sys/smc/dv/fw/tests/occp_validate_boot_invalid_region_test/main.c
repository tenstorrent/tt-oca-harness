/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Validate and Boot Invalid Region Test
 *
 * This test verifies that the VALIDATE_AND_BOOT command properly handles
 * addresses outside the valid region (OCCP_TEST_BASE_ADDR to OCCP_TEST_UPPER_ADDR).
 * The ROM should log an error for invalid addresses and not jump to them.
 * After the invalid command, additional commands are sent to verify the ROM
 * is still responsive and in the OCCP processing loop.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include <string.h>
int exp_num_validate_security_errors = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_validate_security_errors = 0;
    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        increment_cmd_count(ctx);
        simputshex32("SMC Status: ", status_data);
        if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         OCCP_SPEC_ERROR_VALIDATE_ADDRESS_FAILED, false)) {
            num_validate_security_errors++;
        }
    }
    if (num_validate_security_errors != exp_num_validate_security_errors) {
        simputshex32("FAIL: Expected ", exp_num_validate_security_errors);
        simputshex32(" validate security errors, got ", num_validate_security_errors);
        ctx->overall_result = false;
        return;
    } else {
        simputshex32("PASS: ", exp_num_validate_security_errors);
        simputs(" validate security errors found\n");
    }
}
static void run_validate_boot_invalid_region_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Validate and Boot Invalid Region Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    // Execute some random OCCP commands first for baseline
    simputs("=== Random OCCP Commands (5 commands) ===\n");
    execute_random_commands(ctx, 5);

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    simputs("=== Test 1: Validate and Boot with address below valid range ===\n");

    // Test 1: Address below valid range
    uint64_t invalid_addr_below =
        (ctx->test_base_addr - 1 - (get_random_int() % 0x5000)) & 0xfffffffc;
    simputshex64("Attempting VALIDATE_AND_BOOT to invalid address (below range): 0x",
                 invalid_addr_below);
    simputshex64("Valid range is: 0x", ctx->test_base_addr);
    simputshex64(" to 0x", OCCP_TEST_UPPER_ADDR);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, invalid_addr_below);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_SUCCESS;

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (below range)\n");
        ctx->overall_result = false;
        return;
    }
    exp_num_validate_security_errors++;

    simputs("PASS: VALIDATE_AND_BOOT command issued successfully (below range)\n");

    simputs("=== Test 2: Validate and Boot with address just below valid range ===\n");
    uint64_t invalid_addr_below_valid =
        (ctx->test_base_addr - 1 - (get_random_int() % 0x10)) & 0xfffffffc;
    simputshex64("Attempting VALIDATE_AND_BOOT to invalid address (just below range): 0x",
                 invalid_addr_below_valid);
    simputshex64("Valid range is: 0x", ctx->test_base_addr);
    simputshex64(" to 0x", OCCP_TEST_UPPER_ADDR);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, invalid_addr_below_valid);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_SUCCESS;

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (just below range)\n");
        ctx->overall_result = false;
        return;
    }
    exp_num_validate_security_errors++;
    simputs("PASS: VALIDATE_AND_BOOT command issued successfully (just below range)\n");

    if (is_secure_mode()) {
        simputs("=== Test 3: Validate and Boot with address above valid range ===\n");

        // Test 2: Address above valid range
        uint64_t invalid_addr_above =
            (OCCP_TEST_UPPER_ADDR + (get_random_int() % 0x5000)) & 0xfffffffc;
        simputshex64("Attempting VALIDATE_AND_BOOT to invalid address (above range): 0x",
                     invalid_addr_above);

        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, invalid_addr_above);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_SUCCESS;

        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (above range)\n");
            ctx->overall_result = false;
            return;
        }
        exp_num_validate_security_errors++;

        simputs("PASS: VALIDATE_AND_BOOT command issued successfully (above range)\n");

        simputs("=== Test 4: Validate and Boot with address just above valid range ===\n");

        // Test 4: Address just above valid range
        uint64_t invalid_addr_above_valid =
            (OCCP_TEST_UPPER_ADDR + (get_random_int() % 0x10)) & 0xfffffffc;
        simputshex64("Attempting VALIDATE_AND_BOOT to invalid address (just above range): 0x",
                     invalid_addr_above_valid);
        simputshex64("Valid range is: 0x", ctx->test_base_addr);
        simputshex64(" to 0x", OCCP_TEST_UPPER_ADDR);

        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, invalid_addr_above_valid);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_SUCCESS;

        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (just above range)\n");
            ctx->overall_result = false;
            return;
        }
        exp_num_validate_security_errors++;

        simputs("PASS: VALIDATE_AND_BOOT command issued successfully (just above range)\n");
    }
    // relatch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    // send invalid commands in protected region
    simputs("=== Test 5: Validate and Boot with invalid commands in protected region ===\n");
    for (int i = 0; i < 4; i++) {
        uint64_t invalid_addr =
            (SMC_SRAM_BASE_ADDR + (get_random_int() % (OCCP_TEST_BASE_ADDR - SMC_SRAM_BASE_ADDR))) &
            0xfffffffc;
        simputshex64("Attempting VALIDATE_AND_BOOT to invalid address: 0x", invalid_addr);
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, invalid_addr);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_SUCCESS;
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (invalid commands in "
                    "protected region)\n");
            ctx->overall_result = false;
            return;
        }
        exp_num_validate_security_errors++;

        simputs("PASS: VALIDATE_AND_BOOT command issued successfully (invalid commands in "
                "protected region)\n");
    }

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    read_and_validate_smc_status_buffer(ctx);

    // Execute more commands to verify ROM is still responsive
    simputs("=== Random OCCP Commands (10 commands after above-range test) ===\n");
    execute_random_commands(ctx, 5);

    simputs("=== Test 5: Validate and Boot with valid address for comparison ===\n");

    // Test 5: Valid address for comparison
    uint64_t valid_addr =
        (ctx->test_base_addr + (get_random_int() % (OCCP_TEST_UPPER_ADDR - ctx->test_base_addr))) &
        0xfffffffc;
    simputshex64("Attempting VALIDATE_AND_BOOT to valid address: 0x", valid_addr);

    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, valid_addr);
    increment_cmd_count(ctx);

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command (valid range)\n");
        ctx->overall_result = false;
        return;
    }

    simputs("PASS: VALIDATE_AND_BOOT command issued successfully (valid range)\n");

    // NOTE: After a successful validate_boot command in secure mode, the ROM enters
    // a wait state for SEP validation. We won't be able to send more commands after this.
    simputs("ROM should now be in validation wait state - test complete\n");
}

static void finalize_test_results(test_context_t *ctx) {
    // Signal completion to cocotb by writing to the master's scratchpad
    if (ctx->overall_result) {
        simputs("\nVALIDATE AND BOOT INVALID REGION C-TEST PASSED! Signaling cocotb.\n");
        test_pass(0);
    } else {
        simputs("\nVALIDATE AND BOOT INVALID REGION C-TEST FAILED! Signaling cocotb.\n");
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    // Set up test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;                     // Start of valid range
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR; // End of valid range
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    // Run the test
    run_validate_boot_invalid_region_test(&test_ctx);

    // Finalize and report results
    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }

    return 0;
}
