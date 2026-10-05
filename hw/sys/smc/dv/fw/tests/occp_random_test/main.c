/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Runs random OCCP commands, checks GET_STATUS, then drains the SEP and SMC status
 * ring buffers.
 */

#include "occp_test_common.h"

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting Random OCCP Protocol Test ===\n");

    ctx->overall_result = true;

    int retval;
    uint32_t status_data = 0;

    int exp_interface_status = 0x1;
    int exp_boot_status = 0x5;

    simputs("=== Random OCCP Commands Test (25 commands) ===\n");
    execute_random_commands(ctx, 5);

    retval = occp_send_get_status_command(ctx, ctx->slave_addr, &status_data);
    if (retval == OCCP_SUCCESS) {
        check_occp_status_data(ctx, status_data, exp_interface_status, exp_boot_status);
        increment_cmd_count(ctx);
    } else {
        simputs("GET_STATUS: FAIL\n");
        ctx->overall_result = false;
    }

    do {
        retval = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval == OCCP_SUCCESS) {
            simputshex32("SEP Status: ", status_data);
            simputs("GET_SEP_STATUS: PASS\n");
        } else {
            simputs("GET_SEP_STATUS: FAIL\n");
            ctx->overall_result = false;
        }
    } while (status_data != 0 && retval == OCCP_SUCCESS);

    do {
        retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval == OCCP_SUCCESS) {
            simputshex32("SMC Status: ", status_data);
            simputs("GET_SMC_STATUS: PASS\n");
        } else {
            simputs("GET_SMC_STATUS: FAIL\n");
            ctx->overall_result = false;
        }
    } while (status_data != 0 && retval == OCCP_SUCCESS);
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
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
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
