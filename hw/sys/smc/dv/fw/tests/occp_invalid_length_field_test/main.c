/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Runs random OCCP traffic with invalid length fields injected, then a JUMP (non-secure
 * mode only) and a VALIDATE_BOOT under injection, and checks the ROM still answers after.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void disable_len_injection(test_context_t *ctx) {
    ctx->invalid_len_err_inject_enable = false;
}
static void enable_len_injection(test_context_t *ctx) {
    ctx->invalid_len_err_inject_enable = true;
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Invalid Length Field Test ===\n");

    ctx->overall_result = true;

    disable_len_injection(ctx);

    simputs("-- Baseline: Running valid commands --\n");
    execute_random_commands(ctx, 1);

    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }

    simputs("-- Enabling global invalid length injection --\n");
    enable_len_injection(ctx);

    execute_random_commands(ctx, 4);

    disable_len_injection(ctx);
    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    enable_len_injection(ctx);

    if (!is_secure_mode()) {
        simputs("-- Sending manual JUMP under injection --\n");
        occp_send_jump_command(ctx, ctx->slave_addr, OCCP_TEST_BASE_ADDR);
        increment_cmd_count(ctx);
    }

    simputs("-- Sending manual VALIDATE_BOOT under injection --\n");
    occp_send_validate_boot_command(ctx, ctx->slave_addr, OCCP_TEST_BASE_ADDR);
    increment_cmd_count(ctx);

    simputs("-- Disabling injection and running valid commands --\n");
    disable_len_injection(ctx);
    execute_random_commands(ctx, 1);

    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }

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
    static test_context_t ctx = {0};

    init_test(0);

    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
        return -1;
    }

    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    ctx.overall_result = true;
    ctx.sram_scoreboard_idx = 0;
    ctx.cmd_count = 0;
    ctx.exp_occp_last_error = 0;
    ctx.exp_response_code = OCCP_ERROR_NONE;

    run_test_suite(&ctx);

    finalize_test_results(&ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
