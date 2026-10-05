/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends VALIDATE_AND_BOOT in non-secure mode and checks that the ROM answers it without an error
 * response, that GET_STATUS reports the expected command count and interface status, and that
 * the ROM keeps serving OCCP commands.
 */

#include "occp_test_common.h"

static void run_validate_boot_rejection_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Validate and Boot Rejection Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    simputs("=== Random OCCP Commands (10 before rejection test) ===\n");
    execute_random_commands(ctx, 10);

    simputs("=== Validate and Boot Rejection Test ===\n");

    uint64_t random_addr = ctx->test_base_addr +
                           (get_random_int() % (ctx->test_upper_addr_bound - ctx->test_base_addr));
    simputshex64("Attempting VALIDATE_AND_BOOT to random address: ", random_addr);
    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, random_addr);
    increment_cmd_count(ctx);

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to issue VALIDATE_AND_BOOT command\n");
        ctx->overall_result = false;
        return;
    }

    retval = occp_send_get_status_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get status after command\n");
        ctx->overall_result = false;
        return;
    }

    int exp_interface_status = 0x1;
    int exp_boot_status = 0x5;
    check_occp_status_data(ctx, status_data, exp_interface_status, exp_boot_status);
    increment_cmd_count(ctx);

    simputs("=== Random OCCP Commands (10 after rejection test) ===\n");
    execute_random_commands(ctx, 10);

    simputs("Validate and Boot rejection test passed\n");
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("\nVALIDATE AND BOOT REJECTION C-TEST PASSED! Signaling cocotb.\n");
        test_pass(0);
    } else {
        simputs("\nVALIDATE AND BOOT REJECTION C-TEST FAILED! Signaling cocotb.\n");
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
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_validate_boot_rejection_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
}
