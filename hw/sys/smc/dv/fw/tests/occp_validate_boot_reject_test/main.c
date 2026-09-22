/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * VALIDATE_AND_BOOT is refused when the manifest address is inside the
 * ROM-owned region. The ROM has no security-mode gate on this command;
 * smc_occp_check_addr_access_allowed() returns OCCP_ERROR_ACCESS_VIOLATION
 * (smc_occp_status.h) for that region in both modes, and GET_OCCP_ERROR_CODE
 * must read that latch back.
 */

#include "occp_test_common.h"
#include <string.h>

/* First ROM-owned word. FW SMC_SRAM_BASE_ADDR is ROM SMC_ROM_DATA_BASE;
 * OCCP_TEST_BASE_ADDR is the first address the ROM will serve. */
#define ROM_OWNED_MANIFEST_ADDR SMC_SRAM_BASE_ADDR

/* Latched last-error, smc_occp_status.h OCCP_ERROR_ACCESS_VIOLATION. */
#define OCCP_LATCHED_ACCESS_VIOLATION 0x02

static void run_validate_boot_rejection_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Validate and Boot Rejection Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    simputs("=== Random OCCP Commands (10 before rejection test) ===\n");
    execute_random_commands(ctx, 10);

    simputs("=== Validate and Boot Rejection Test ===\n");
    simputshex64("VALIDATE_AND_BOOT manifest in the ROM-owned region: ",
                 ROM_OWNED_MANIFEST_ADDR);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, ROM_OWNED_MANIFEST_ADDR);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: VALIDATE_AND_BOOT did not answer Invalid_Address\n");
        ctx->overall_result = false;
        return;
    }

    ctx->exp_occp_last_error = OCCP_LATCHED_ACCESS_VIOLATION;
    ctx->check_occp_last_error = true;
    retval = occp_send_get_occp_error_code_command(ctx, ctx->slave_addr, &status_data);
    increment_cmd_count(ctx);
    ctx->check_occp_last_error = false;
    if (retval != OCCP_SUCCESS || !ctx->overall_result) {
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to issue GET_OCCP_ERROR_CODE\n");
        }
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
    test_ctx.check_occp_last_error = false;

    run_validate_boot_rejection_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }

    return 0;
}
