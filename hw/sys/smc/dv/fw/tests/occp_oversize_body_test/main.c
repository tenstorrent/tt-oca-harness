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
    ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    ctx.overall_result = true;
    ctx.cmd_count = 0;
    ctx.exp_occp_last_error = 0;

    ctx.header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx.body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx.invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    execute_random_commands(&ctx, 5);
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);

    ctx.inject_oversize_body_err = true;
    ctx.exp_response_code = OCCP_OVERSIZE_MSG;
    execute_random_commands(&ctx, 4);

    ctx.inject_oversize_body_err = false;
    ctx.exp_response_code = OCCP_ERROR_NONE;

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    ctx.inject_oversize_body_err = true;
    ctx.exp_response_code = OCCP_OVERSIZE_MSG;

    if (!is_secure_mode()) {
        occp_send_jump_command(&ctx, ctx.slave_addr, OCCP_TEST_BASE_ADDR);
        increment_cmd_count(&ctx);
    }
    occp_send_validate_boot_command(&ctx, ctx.slave_addr, OCCP_TEST_BASE_ADDR);
    increment_cmd_count(&ctx);

    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    ctx.inject_oversize_body_err = false;
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
}
