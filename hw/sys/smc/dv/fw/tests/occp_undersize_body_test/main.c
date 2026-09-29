/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

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

    ctx.inject_undersize_body_err = true;
    ctx.exp_response_code = OCCP_INCOMPLETE_MSG;
    execute_random_commands(&ctx, 10);

    if (!is_secure_mode()) {
        occp_send_jump_command(&ctx, ctx.slave_addr, OCCP_TEST_BASE_ADDR);
    }
    occp_send_validate_boot_command(&ctx, ctx.slave_addr, OCCP_TEST_BASE_ADDR);

    ctx.inject_undersize_body_err = false;
    ctx.exp_response_code = OCCP_ERROR_NONE;
    execute_random_commands(&ctx, 5);

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
