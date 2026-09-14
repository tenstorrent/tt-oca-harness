/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Master Test Suite - Main Entry Point
 *
 *
 * TEST SELECTION:
 * To run specific tests, modify the RUN_TEST_* flags in the occp_test_common.h file:
 * - Set to 1 to enable a test category
 * - Set to 0 to disable a test category
 *
 * Test Categories:
 * - RUN_TEST_GET_COMMANDS: GET_VERSION, GET_STATUS, GET_SEP_STATUS, GET_SMC_STATUS
 * - RUN_TEST_BASIC_RW: Basic READ/WRITE operations (8-byte, 4-byte, 1-byte)
 * - RUN_TEST_ALIGNMENT: Address alignment testing
 * - RUN_TEST_LARGE_DATA: Large data transfer (16 bytes)
 * - RUN_TEST_ZERO_LENGTH: Zero length transfer edge case
 * - RUN_TEST_PATTERNS: Pattern verification test
 * - RUN_TEST_BOUNDARIES: Memory boundary testing
 * - RUN_TEST_SIZE_LIMITS: I3C Transfer size limits
 * - RUN_TEST_STATUS_DUMP: Ring buffer status dumping
 */

#include "occp_test_common.h"

// Function declarations for individual test modules
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
    // Status dump test - informational only
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

    // Initialize interface and discover devices
    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    // Set up test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.overall_result = true;
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
