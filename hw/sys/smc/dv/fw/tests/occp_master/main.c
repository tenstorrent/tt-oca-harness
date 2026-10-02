/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Runs the OCCP master suite: GET commands, READ/WRITE sizes, alignment, large data,
 * zero length, patterns, boundaries, size limits and a status ring buffer dump.
 * The RUN_TEST_* flags in occp_test_common.h select which categories are built.
 */

#include "occp_test_common.h"

bool run_get_commands_tests(test_context_t *ctx);
bool run_basic_rw_tests(test_context_t *ctx);
bool run_alignment_tests(test_context_t *ctx);
bool run_large_data_tests(test_context_t *ctx);
bool run_zero_length_tests(test_context_t *ctx);
bool run_pattern_tests(test_context_t *ctx);
bool run_boundary_tests(test_context_t *ctx);
bool run_size_limit_tests(test_context_t *ctx);
bool run_status_dump_tests(test_context_t *ctx);

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting Comprehensive OCCP Protocol Test ===\n");

    ctx->overall_result = true;

#if RUN_TEST_GET_COMMANDS
    ctx->overall_result &= run_get_commands_tests(ctx);
#else
    simputs("Skipping GET command tests (disabled)\n");
#endif

#if RUN_TEST_BASIC_RW
    ctx->overall_result &= run_basic_rw_tests(ctx);
#else
    simputs("Skipping basic READ/WRITE tests (disabled)\n");
#endif

#if RUN_TEST_ALIGNMENT
    ctx->overall_result &= run_alignment_tests(ctx);
#else
    simputs("Skipping address alignment tests (disabled)\n");
#endif

#if RUN_TEST_LARGE_DATA
    ctx->overall_result &= run_large_data_tests(ctx);
#else
    simputs("Skipping large data transfer tests (disabled)\n");
#endif

#if RUN_TEST_ZERO_LENGTH
    ctx->overall_result &= run_zero_length_tests(ctx);
#else
    simputs("Skipping zero length transfer tests (disabled)\n");
#endif

#if RUN_TEST_PATTERNS
    ctx->overall_result &= run_pattern_tests(ctx);
#else
    simputs("Skipping pattern verification tests (disabled)\n");
#endif

#if RUN_TEST_BOUNDARIES
    ctx->overall_result &= run_boundary_tests(ctx);
#else
    simputs("Skipping boundary testing (disabled)\n");
#endif

#if RUN_TEST_SIZE_LIMITS
    ctx->overall_result &= run_size_limit_tests(ctx);
#else
    simputs("Skipping I3C transfer size limit tests (disabled)\n");
#endif

    simputs("=== OCCP Protocol Test Summary ===\n");

#if RUN_TEST_STATUS_DUMP
    run_status_dump_tests(ctx);
#else
    simputs("Skipping ring buffer status dump (disabled)\n");
#endif
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
    } else {
        simputs("SOME TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
    }

    occp_send_write_command(ctx, ctx->slave_addr, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0),
                            (uint8_t *)&result_code, sizeof(result_code));
}

int main(void) {
    static test_context_t test_ctx = {0};

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
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
