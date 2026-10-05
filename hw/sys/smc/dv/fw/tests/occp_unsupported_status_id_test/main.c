/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends GET_OCCP_BOOT_STATUS with a randomly injected unsupported status_id and expects the
 * Unsupported error response; the command helpers treat that response as success.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void run_test_suite(test_context_t *ctx) {
    simputs("=== OCCP Unsupported Status ID Injection Test ===\n");

    execute_random_commands(ctx, 5);
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    ctx->unsupported_status_id_inject_enable = true;
    ctx->exp_response_code = OCCP_UNSUPPORTED_STATUS;

    uint32_t status = 0;
    for (int i = 0; i < 4; i++) {
        int rc = occp_send_get_occp_boot_status_command(ctx, ctx->slave_addr, &status);
        if (rc != OCCP_SUCCESS) {
            simputs("FAIL: GET_OCCP_BOOT_STATUS under unsupported ID injection\n");
            ctx->overall_result = false;
        }
        increment_cmd_count(ctx);
    }
    ctx->unsupported_status_id_inject_enable = false;
    ctx->exp_response_code = OCCP_ERROR_NONE;

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    execute_random_commands(ctx, 5);
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
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }
}
