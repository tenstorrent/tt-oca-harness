/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static void reset_injection_config(test_context_t *ctx) {
    ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
}

static void configure_injection(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                occp_crc_inject_mode_t body_mode) {
    ctx->header_crc_err_inject_mode = header_mode;
    ctx->body_crc_err_inject_mode = body_mode;
}

static void clear_consecutive_error_count(test_context_t *ctx) {
    uint32_t status = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
}

static bool run_header_body_combo(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                  occp_crc_inject_mode_t body_mode) {
    configure_injection(ctx, header_mode, body_mode);
    uint8_t data[MAX_OCCP_READ_SIZE];

    for (int i = 0; i < 2; i++) {
        // Body-CRC cases skip the commands that carry no request body.
        int cmd_low_bound =
            (header_mode == OCCP_CRC_INJECT_NONE) ? OCCP_GET_SEP_STATUS : OCCP_GET_VERSION;
        int cmd_upper_bound = is_secure_mode() ? OCCP_VALIDATE_BOOT : OCCP_JUMP;
        int random_cmd = get_random_int() % (cmd_upper_bound - cmd_low_bound + 1) + cmd_low_bound;
        int retval;
        int size;
        uint32_t addr = (get_random_int() % (ctx->test_upper_addr_bound - ctx->test_base_addr) +
                         ctx->test_base_addr) &
                        0xfffffffc;
        uint32_t status;
        switch (random_cmd) {
        case OCCP_GET_VERSION:
            retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_VERSION_BOOT:
            retval = occp_send_get_version_boot_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_STATUS:
            retval = occp_send_get_status_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_SEP_STATUS:
            retval = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_SMC_STATUS:
            retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_OCCP_BOOT_STATUS:
            retval = occp_send_get_occp_boot_status_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_OCCP_INTERFACE_STATUS:
            retval = occp_send_get_occp_interface_status_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_OCCP_COMMAND_COUNT:
            retval = occp_send_get_occp_command_count_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_GET_OCCP_ERROR_CODE:
            retval = occp_send_get_occp_error_code_command(ctx, ctx->slave_addr, &status);
            break;
        case OCCP_READ:
            size = get_random_int() % (MAX_OCCP_READ_SIZE) + 1;
            retval = occp_send_read_command(ctx, ctx->slave_addr, addr, data, size);
            break;
        case OCCP_WRITE:
            size = get_random_int() % (MAX_OCCP_WRITE_SIZE) + 1;
            for (int i = 0; i < size; i++) data[i] = get_random_int() % 256;
            retval = occp_send_write_command(ctx, ctx->slave_addr, addr, data, size);
            break;
        case OCCP_JUMP:
            retval = occp_send_jump_command(ctx, ctx->slave_addr, addr);
            break;
        case OCCP_VALIDATE_BOOT:
            retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, addr);
            break;
        default:
            retval = OCCP_INVALID_CMD;
            break;
        }
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Command failed\n");
            ctx->overall_result = false;
            return false;
        }
        increment_cmd_count(ctx);
    }
    reset_injection_config(ctx);
    return true;
}

int main(void) {
    static test_context_t ctx = {0};

    init_test(0);

    simputs("=== OCCP CRC Injection Test ===\n");
    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    ctx.overall_result = true;
    ctx.cmd_count = 0;
    ctx.exp_occp_last_error = 0;

    reset_injection_config(&ctx);

    execute_random_commands(&ctx, 5);

    simputs("-- Case 1: Detectable header CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_DETECTABLE, OCCP_CRC_INJECT_NONE);

    simputs("-- Case 2: Possibly undetectable header CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_UNDETECTABLE, OCCP_CRC_INJECT_NONE);

    clear_consecutive_error_count(&ctx);

    simputs("-- Case 3: Undetectable body CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_DETECTABLE);

    simputs("-- Case 4: Possibly undetectable body CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_UNDETECTABLE);

    clear_consecutive_error_count(&ctx);

    simputs("-- Case 5: Corrupt header CRC --\n");
    run_header_body_combo(&ctx, OCCP_CORRUPT_CRC, OCCP_CRC_INJECT_NONE);

    simputs("-- Case 6: Corrupt body CRC --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CORRUPT_CRC);

    reset_injection_config(&ctx);
    clear_consecutive_error_count(&ctx);

    /* CRC-error entries carry no fixed status code, so the SMC status buffer is not
     * validated here. */

    execute_random_commands(&ctx, 5);

    if (ctx.overall_result) {
        test_pass(0);
    } else {
        test_fail(0);
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
