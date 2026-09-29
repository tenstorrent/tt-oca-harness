/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Invalid Message Length (Zero-Length Body) Test
 *
 * Sends READ and WRITE commands while forcing the OCCP header length field to 0
 * using the test context length injection. Expects the target to return an
 * error response with code INVALID_MESSAGE_LENGTH. The command helpers treat
 * that as success under injection, mirroring the unsupported status ID test style.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void run_zero_len_body_cases(test_context_t *ctx) {
    uint64_t range = ctx->test_upper_addr_bound - ctx->test_base_addr;
    uint64_t addr = ctx->test_base_addr + (get_random_int() % (range ? range : 4));
    addr &= 0xfffffffffffffffcULL;
    uint8_t data[8] = {0};

    simputs("=== OCCP Invalid Message Length (force zero) ===\n");

    ctx->invalid_message_length_zero_inject_enable = true;
    ctx->exp_response_code = OCCP_INVALID_HEADER;

    for (int i = 0; i < 10; i++) {
        int send_write = get_random_int() % 2;
        if (send_write) {
            int rc = occp_send_write_command(ctx, ctx->slave_addr, addr, data, 8);
            if (rc != OCCP_SUCCESS) {
                simputs("FAIL: WRITE under zero-length injection\n");
                ctx->overall_result = false;
            }
        } else {
            int rc = occp_send_read_command(ctx, ctx->slave_addr, addr, data, 8);
            if (rc != OCCP_SUCCESS) {
                simputs("FAIL: READ under zero-length injection\n");
                ctx->overall_result = false;
            }
        }
        increment_cmd_count(ctx);
    }
    ctx->exp_response_code = OCCP_ERROR_NONE;

    ctx->invalid_message_length_zero_inject_enable = false;
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

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    execute_random_commands(&test_ctx, 5);

    run_zero_len_body_cases(&test_ctx);

    execute_random_commands(&test_ctx, 5);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }
    return 0;
}
