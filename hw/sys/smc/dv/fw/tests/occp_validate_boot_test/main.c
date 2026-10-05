/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends VALIDATE_AND_BOOT with a random manifest address inside the OCCP window and records the
 * address for the harness, which checks that the ROM hands the same address on to SEP, flags the
 * manifest ready and then halts.
 */

#include "occp_test_common.h"
#include "smc_defines.h"

static void run_validate_boot_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Validate and Boot Test ===\n");

    ctx->overall_result = true;

    simputs("=== Random OCCP Commands (10 commands) ===\n");
    execute_random_commands(ctx, 10);

    simputs("=== Test validate and boot ===\n");
    uint32_t random_manifest_addr =
        (ctx->test_base_addr +
         (get_random_int() %
          (ctx->test_upper_addr_bound - (sizeof(uint64_t) - 1) - ctx->test_base_addr))) &
        0xfffffffc;
    simputshex32("Random manifest address: ", random_manifest_addr);
    write_scratch(8, random_manifest_addr);

    simputs("Sending VALIDATE_AND_BOOT command...\n");
    int retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, random_manifest_addr);

    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: occp_send_validate_boot_command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("PASS: occp_send_validate_boot_command succeeded\n");
    }
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("\nVALIDATE AND BOOT C-TEST PASSED! Signaling cocotb.\n");
        test_pass(0);
    } else {
        simputs("\nVALIDATE AND BOOT C-TEST FAILED! Signaling cocotb.\n");
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

    run_validate_boot_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
}
