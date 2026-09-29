/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static int exp_num_cmd_failed_errors = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_cmd_failed_errors = 0;
    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        simputshex32("SMC Status: ", status_data);
        if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         OCCP_SPEC_ERROR_CMD_FAILED, false)) {
            num_cmd_failed_errors++;
        }
    }
    if (num_cmd_failed_errors != exp_num_cmd_failed_errors) {
        simputshex32("FAIL: Expected ", exp_num_cmd_failed_errors);
        simputshex32(" CMD_FAILED errors, got ", num_cmd_failed_errors);
        ctx->overall_result = false;
        return;
    } else {
        simputshex32("PASS: ", exp_num_cmd_failed_errors);
        simputs(" CMD_FAILED errors found\n");
    }
}

static void reset_injection_config(test_context_t *ctx) {
    ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
}

static void configure_injection(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                occp_crc_inject_mode_t body_mode) {
    ctx->header_crc_err_inject_mode = header_mode;
    ctx->body_crc_err_inject_mode = body_mode;
}

static bool run_header_body_combo(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                  occp_crc_inject_mode_t body_mode) {
    /* Force error injection on this transaction */
    bool expect_header_error = (header_mode == OCCP_CRC_INJECT_DETECTABLE);
    bool expect_body_error = (!expect_header_error) && (body_mode == OCCP_CRC_INJECT_DETECTABLE);
    bool accept_any = (!expect_header_error && !expect_body_error);
    configure_injection(ctx, header_mode, body_mode);
    uint8_t data[MAX_OCCP_READ_SIZE];

    for (int i = 0; i < 2; i++) {
        // don't send get version for body corruption (no body)
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

    /* Warm-up valid commands */
    execute_random_commands(&ctx, 5);

    /* Four combinations: detectable/undetectable for header and body */
    // 1) Detectable header CRC error -> expect header error
    simputs("-- Case 1: Detectable header CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_DETECTABLE, OCCP_CRC_INJECT_NONE);
    exp_num_cmd_failed_errors += 2;

    // 2) Possibly undetectable header CRC error -> expect header error
    simputs("-- Case 2: Possibly undetectable header CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_UNDETECTABLE, OCCP_CRC_INJECT_NONE);
    exp_num_cmd_failed_errors += 2;

    // relatch to recover
    execute_random_commands(&ctx, 1);

    // 3) detectable body -> expect body error
    simputs("-- Case 3: Undetectable body CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_DETECTABLE);
    exp_num_cmd_failed_errors += 2;

    // 4) undetectable body -> accept error or non-error
    simputs("-- Case 4: Possibly undetectable body CRC error --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_UNDETECTABLE);
    exp_num_cmd_failed_errors += 2;

    execute_random_commands(&ctx, 1);

    // 5) Corrupt header crc -> expect header error
    simputs("-- Case 5: Corrupt header CRC --\n");
    run_header_body_combo(&ctx, OCCP_CORRUPT_CRC, OCCP_CRC_INJECT_NONE);
    exp_num_cmd_failed_errors += 2;

    // 6) Corrupt body crc -> expect body error
    simputs("-- Case 6: Corrupt body CRC --\n");
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CORRUPT_CRC);
    exp_num_cmd_failed_errors += 2;

    reset_injection_config(&ctx);

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
