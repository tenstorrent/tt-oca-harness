/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * In non-secure mode, issues JUMPs into the protected SRAM region below the OCCP test range,
 * checks each is rejected with INVALID_ADDRESS and a JUMP_READ_FAILED status entry, and that
 * the ROM still answers afterwards.
 */

#include "occp_test_common.h"
#include "smc_defines.h"

int exp_num_jump_security_errors = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_jump_security_errors = 0;
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
                                         OCCP_SPEC_ERROR_JUMP_READ_FAILED, false)) {
            num_jump_security_errors++;
        }
    }
    if (num_jump_security_errors != exp_num_jump_security_errors) {
        simputshex32("FAIL: Expected ", exp_num_jump_security_errors);
        simputshex32(" jump read errors, got ", num_jump_security_errors);
        ctx->overall_result = false;
        return;
    } else {
        simputshex32("PASS: ", exp_num_jump_security_errors);
        simputs(" jump read errors found\n");
    }
}

static void run_jump_invalid_region_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Jump Invalid Region Test (Unsecure Mode Only) ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    uint64_t protected_region_base = SMC_SRAM_BASE_ADDR;
    uint64_t protected_region_upper = OCCP_TEST_BASE_ADDR;

    simputs("=== Random OCCP Commands (5 commands) ===\n");
    execute_random_commands(ctx, 5);

    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    simputs("=== Test 1: Jump to protected region base address ===\n");

    uint64_t jump_addr_base = protected_region_base;
    simputshex64("Attempting JUMP to protected region base: 0x", jump_addr_base);
    simputshex64("Protected region is: 0x", protected_region_base);
    simputshex64(" to 0x", protected_region_upper);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    retval = occp_send_jump_command(ctx, ctx->slave_addr, jump_addr_base);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_SUCCESS;

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue JUMP command (base address)\n");
        ctx->overall_result = false;
        return;
    }
    exp_num_jump_security_errors++;

    simputs("PASS: JUMP command issued successfully (base address)\n");

    simputs("=== Test 2: Jump to protected region upper boundary ===\n");

    uint64_t jump_addr_upper = (protected_region_upper - 4) & 0xfffffffc;
    simputshex64("Attempting JUMP to protected region upper boundary: 0x", jump_addr_upper);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    retval = occp_send_jump_command(ctx, ctx->slave_addr, jump_addr_upper);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_SUCCESS;

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue JUMP command (upper boundary)\n");
        ctx->overall_result = false;
        return;
    }
    exp_num_jump_security_errors++;
    simputs("PASS: JUMP command issued successfully (upper boundary)\n");

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    simputs("=== Test 3: Jump to random offsets in protected region ===\n");

    for (int i = 0; i < 4; i++) {
        uint64_t region_size = protected_region_upper - protected_region_base;
        uint64_t random_offset = (get_random_int() % region_size) & 0xfffffffc;
        uint64_t jump_addr_random1 = protected_region_base + random_offset;
        simputshex64("Attempting JUMP to random protected address: 0x", jump_addr_random1);

        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        retval = occp_send_jump_command(ctx, ctx->slave_addr, jump_addr_random1);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_SUCCESS;

        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to issue JUMP command (random offset)\n");
            ctx->overall_result = false;
        }
        exp_num_jump_security_errors++;
    }

    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    read_and_validate_smc_status_buffer(ctx);

    simputs("=== Random OCCP Commands (10 commands after invalid jump tests) ===\n");
    execute_random_commands(ctx, 5);

    simputs("=== Jump Invalid Region Test Complete ===\n");
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("\nJUMP INVALID REGION C-TEST PASSED! Signaling cocotb.\n");
        test_pass(0);
    } else {
        simputs("\nJUMP INVALID REGION C-TEST FAILED! Signaling cocotb.\n");
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

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_jump_invalid_region_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
}
