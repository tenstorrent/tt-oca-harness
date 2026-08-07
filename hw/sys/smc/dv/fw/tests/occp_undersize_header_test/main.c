#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

// void run_undersize_sequence(test_context_t *ctx)
//{
//     uint32_t status32 = 0;
//     uint8_t buf4[4] = {0};
//     uint8_t recv1[1] = {0};
//
//     if (occp_send_get_status_command(ctx, ctx->slave_addr, &status32) != OCCP_SUCCESS) {
//         simputs("Undersize GET_STATUS failed\n");
//         ctx->overall_result = false;
//     }
//
//     if (occp_send_get_version_command(ctx, ctx->slave_addr, &status32) != OCCP_SUCCESS) {
//         simputs("Undersize GET_VERSION failed\n");
//         ctx->overall_result = false;
//     }
//
//     if (occp_send_write_command(ctx, ctx->slave_addr, ctx->test_base_addr, buf4, sizeof(buf4)) !=
//     OCCP_SUCCESS) {
//         simputs("Undersize WRITE failed\n");
//         ctx->overall_result = false;
//     }
//
//     if (occp_send_read_command(ctx, ctx->slave_addr, ctx->test_base_addr, recv1, sizeof(recv1))
//     != OCCP_SUCCESS) {
//         simputs("Undersize READ failed\n");
//         ctx->overall_result = false;
//     }
// }

int main(void) {
    static test_context_t ctx = {0};

    init_test(0);

    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
        return 0;
    }

    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    ctx.overall_result = true;
    ctx.cmd_count = 0;
    ctx.exp_occp_last_error = 0;

    ctx.header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx.body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx.invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    execute_random_commands(&ctx, 5);

    /* Enable undersize header injection */
    ctx.inject_undersize_header_err = true;
    execute_random_commands(&ctx, 10);

    // disable and recover
    ctx.inject_undersize_header_err = false;
    execute_random_commands(&ctx, 5);

    // ctx.timeout = 1000; /* ensure expected timeout path progresses */

    uint32_t result_code =
        ctx.overall_result ? SMC_SCRATCHPAD_SIM_PASS_CODE : SMC_SCRATCHPAD_SIM_FAIL_CODE;

    if (ctx.overall_result) {
        test_pass(0);
    } else {
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }
    return 0;
}
