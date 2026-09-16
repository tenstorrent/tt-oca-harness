/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Jump Rejection Test
 *
 * Issues JUMP commands to random in-range addresses, expects each to be rejected,
 * and checks the SMC status buffer for JUMP_SECURITY errors.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h> // For memcpy

static void validate_smc_status_buffer_for_jump_reject(test_context_t *ctx) {
    simputs("=== Validating SMC status buffer for JUMP rejection ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }

    uint32_t smc_status = 0;
    int retval;
    int num_jump_security_errors = 0;
    while (true) {
        retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &smc_status);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to read SMC status\n");
            ctx->overall_result = false;
            break;
        }
        increment_cmd_count(ctx);
        if (smc_status == 0) {
            break;
        }
        simputshex32("SMC Status Entry: 0x", smc_status);
        if (occp_status_matches_expected(smc_status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         OCCP_SPEC_ERROR_JUMP_SECURITY, false)) {
            num_jump_security_errors++;
        }
    }
    if (num_jump_security_errors < 1) {
        simputs("FAIL: Expected at least 1 JUMP_SECURITY error in SMC status buffer\n");
        ctx->overall_result = false;
    } else {
        simputshex32("PASS: JUMP_SECURITY errors found: ", (uint32_t)num_jump_security_errors);
    }
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Jump Rejection Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    // Execute 10 random OCCP commands before jump
    simputs("=== Random OCCP Commands Test (10 commands before jump) ===\n");
    execute_random_commands(ctx, 10);

    simputs("=== Jump Rejection Test ===\n");

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // jump directly to a random address (should be rejected)
    for (int i = 0; i < 4; i++) {
        uint32_t random_jump_addr =
            ctx->test_base_addr +
            (get_random_int() % (ctx->test_upper_addr_bound - ctx->test_base_addr));
        simputshex32("Attempting jump to random address: ", random_jump_addr);
        ctx->exp_response_code = OCCP_INVALID_MSGID;
        retval = occp_send_jump_command(ctx, ctx->slave_addr, random_jump_addr);
        if (retval != OCCP_SUCCESS) {
            simputs("Failed to issue jump command\n");
            ctx->overall_result = false;
            return;
        }
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;
    }

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Validate that SMC status buffer logged the jump rejection
    validate_smc_status_buffer_for_jump_reject(ctx);

    // Random OCCP commands after the rejected jumps confirm the ROM keeps responding
    simputs("=== Random OCCP Commands Test (10 commands after jump rejection) ===\n");
    execute_random_commands(ctx, 5);

    simputs("Jump rejection test passed\n");
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

    // Finalize and report results
    finalize_test_results(&test_ctx);

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
