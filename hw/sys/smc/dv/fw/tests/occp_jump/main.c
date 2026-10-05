/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Reads the payload base and entry offset that the loader publishes and issues an OCCP JUMP to
 * the entry point. The payload reports the pass after the jump; this image reports only a failure.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Jump Test ===\n");

    ctx->overall_result = true;
    int retval;

    simputs("=== Jump Command Test ===\n");

    // The payload base reads as zero until the loader has written the payload.
    uint32_t test_addr = 0;
    while (test_addr == 0) {
        retval = occp_send_read_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_4__REG_ADDR,
                                        (uint8_t *)&test_addr, sizeof(test_addr));
        if (retval != OCCP_SUCCESS) {
            simputs("Failed to read scratch 4\n");
        }
        simputshex32("Test address: ", test_addr);
    }

    // The loader publishes the entry offset before the base, so it is valid once the base is set.
    uint32_t entry_offset = 0;
    retval = occp_send_read_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_5__REG_ADDR,
                                    (uint8_t *)&entry_offset, sizeof(entry_offset));
    if (retval != OCCP_SUCCESS) {
        simputs("Failed to read scratch 5\n");
        ctx->overall_result = false;
        return;
    }
    simputshex32("Entry offset: ", entry_offset);

    retval = occp_send_jump_command(ctx, ctx->slave_addr, test_addr + entry_offset);
    if (retval != OCCP_SUCCESS) {
        simputs("Failed to jump to test address\n");
        ctx->overall_result = false;
        return;
    }
}

static void finalize_test_results(test_context_t *ctx) {
    // A pass is reported after the jump by the payload; only a failure ends the test here.
    if (ctx->overall_result) {
        simputs("Completed bfm test, waiting for ROM to complete!\n");
    } else {
        simputs("BFM failed to jump to test address!\n");
        test_fail(0);
    }
    while (1) {
        __asm__("wfi");
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
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);
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
