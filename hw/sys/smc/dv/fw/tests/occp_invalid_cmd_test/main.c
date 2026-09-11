/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Invalid Command Code Test
 *
 * This test sends commands with invalid OCCP command codes to verify
 * that the ROM properly rejects them and reports appropriate error status.
 *
 * The ROM status buffer preserves only the low byte of an invalid command
 * (SMC_OCCP_ERROR_WITH_DATA): a multi-byte command such as 0xDEAD is stored as
 * 0x101 | 0xAD = 0x1AD.
 */

#include "occp_test_common.h"
#include "smc_test.h"
#include <string.h>

int exp_num_cmd_unknown_errors = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_cmd_unknown_errors = 0;
    // CMD_UNKNOWN is indistinguishable from CMD_FAILED so we will count both and expect twice the
    // number of errors
    exp_num_cmd_unknown_errors *= 2;
    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        simputshex32("SMC Status: ", status_data);
        // will match for both CMD_UNKNOWN and CMD_FAILED
        if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         OCCP_SPEC_ERROR_CMD_UNKNOWN, false)) {
            num_cmd_unknown_errors++;
        }
    }
    if (num_cmd_unknown_errors != exp_num_cmd_unknown_errors) {
        simputshex32("FAIL: Expected ", exp_num_cmd_unknown_errors);
        simputshex32(" CMD_UNKNOWN errors, got ", num_cmd_unknown_errors);
        ctx->overall_result = false;
        return;
    } else {
        simputshex32("PASS: ", exp_num_cmd_unknown_errors);
        simputs(" CMD_UNKNOWN errors found\n");
    }
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Invalid Command Code Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    // Execute a few valid commands first to establish baseline
    simputs("=== Valid Commands Test (baseline) ===\n");
    execute_random_commands(ctx, 1);

    simputs("=== Invalid Header Format Tests (AppID/MsgID) ===\n");

    // Case 1: Valid AppID (Base) with invalid MsgID -> expect Invalid_MsgID
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_MSGID;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Case 2: Invalid AppID with valid MsgID (0) -> expect Invalid_AppID
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Case 3: Invalid AppID and Invalid MsgID -> expect Invalid_AppID precedence
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_BOTH;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // relatch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    simputs("Invalid header tests completed\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // recovery from invalid command
    execute_random_commands(ctx, 1);
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
        test_pass(0);
    } else {
        simputs("SOME TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
        test_fail(0);
    }

    occp_send_write_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
                            (uint8_t *)&result_code, sizeof(result_code));
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
        return -1;
    }

    // Set up test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    // Run the test suite
    run_test_suite(&test_ctx);

    // Read and validate the status buffer
    read_and_validate_smc_status_buffer(&test_ctx);

    // Finalize and report results
    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
