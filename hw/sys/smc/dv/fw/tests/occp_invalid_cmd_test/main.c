/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends OCCP requests with an invalid MsgID, an invalid AppID, and both, and checks that the
 * ROM rejects each and logs the expected number of error entries in the SMC status buffer.
 * With the status-reporting-disable strap set, the status-buffer check is skipped.
 */

#include "occp_test_common.h"
#include "smc_test.h"

int exp_num_cmd_unknown_errors = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_cmd_unknown_errors = 0;
    // The check cannot tell CMD_UNKNOWN from CMD_FAILED, so it counts both and expects twice the
    // number of rejected requests.
    exp_num_cmd_unknown_errors *= 2;
    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        simputshex32("SMC Status: ", status_data);
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

    simputs("=== Valid Commands Test (baseline) ===\n");
    execute_random_commands(ctx, 1);

    simputs("=== Invalid Header Format Tests (AppID/MsgID) ===\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_MSGID;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_BOTH;
    execute_random_commands(ctx, 1);
    exp_num_cmd_unknown_errors += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    simputs("Invalid header tests completed\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    execute_random_commands(ctx, 1);
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        test_pass(0);
    } else {
        simputs("SOME TESTS FAILED!\n");
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_test_suite(&test_ctx);

    read_and_validate_smc_status_buffer(&test_ctx);

    finalize_test_results(&test_ctx);
}
