/*
 * OCCP Master Test Suite - Main Entry Point
 *
 *
 *
 */

#include "occp_test_common.h"
//#include "smc_defines.h"
//#include "smc_test.h"
#include <string.h> // For memcpy

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting Min Size Read/Write OCCP Protocol Test ===\n");

    ctx->overall_result = true;

    int retval;
    uint32_t status_data = 0;

    // TODO: audit these values OCCP spec
    int exp_interface_status = 0x1;
    int exp_boot_status = 0x5;

    // Execute 25 random OCCP commands using shared function
    simputs("=== Min Size Read/Write OCCP Commands Test (25 commands) ===\n");
    execute_min_size_rw_commands(ctx, 25);
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
