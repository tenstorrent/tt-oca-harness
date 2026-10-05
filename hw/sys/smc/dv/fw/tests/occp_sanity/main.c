/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Sanity Test - Version Query
 *
 * Verifies basic OCCP communication from the controller to the target ROM: a
 * GET_VERSION command completes and returns protocol version 1.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting Simple OCCP Sanity Test ===\n");

    ctx->overall_result = true;
    int retval;

    simputs("=== Status Commands Test ===\n");

    int version;
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &version);
    if (retval == OCCP_SUCCESS) {
        simputshex32("OCCP Version: ", version);
        simputs("GET_VERSION: PASS\n");
    } else {
        simputs("GET_VERSION: FAIL\n");
        ctx->overall_result = false;
    }

    if (version != 0x1) {
        simputs("OCCP Version mismatch\n");
        simputshex32("Expected: ", 0x1);
        simputshex32("Actual: ", version);
        ctx->overall_result = false;
    }
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

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;
    test_ctx.sram_scoreboard_idx = 0;

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
