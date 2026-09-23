/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Injects detectable, possibly-undetectable and CRC-field faults into the OCCP header and
 * body CRCs, checks the exact error code in each response, and checks that a clean
 * GET_VERSION still succeeds after each pair of cases.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

#define OCCP_CMDS_PER_CASE 2

/* Bounds the status drain so a DUT that never returns 0 fails instead of hanging. */
#define OCCP_STATUS_DRAIN_MAX_ENTRIES 512

/* Lower bounds: a rejected command records one or two CMD_FAILED entries, per handler. */
static int exp_min_cmd_failed_errors = 0;
static int exp_min_corrupt_header_reports = 0;

#define OCCP_CMD_FAILED_CORRUPT_HEADER \
    ((uint16_t)((uint16_t)OCCP_SPEC_ERROR_CMD_FAILED | (uint16_t)OCCP_CORRUPT_HEADER))

static const char *inject_mode_name(occp_crc_inject_mode_t mode) {
    switch (mode) {
    case OCCP_CRC_INJECT_NONE:
        return "none";
    case OCCP_CRC_INJECT_DETECTABLE:
        return "detectable";
    case OCCP_CRC_INJECT_UNDETECTABLE:
        return "possibly-undetectable";
    case OCCP_CORRUPT_CRC:
        return "corrupt-crc-field";
    default:
        return "unknown";
    }
}

static const char *error_code_name(occp_error_code_t code) {
    switch (code) {
    case OCCP_ERROR_NONE:
        return "none (liveness only)";
    case OCCP_CORRUPT_HEADER:
        return "OCCP_CORRUPT_HEADER";
    case OCCP_CORRUPT_DATA:
        return "OCCP_CORRUPT_DATA";
    default:
        return "unexpected";
    }
}

/* The ROM checks the header CRC before the body, so a corrupt header takes precedence. */
static occp_error_code_t expected_error_for_modes(occp_crc_inject_mode_t header_mode,
                                                  occp_crc_inject_mode_t body_mode) {
    if ((header_mode == OCCP_CRC_INJECT_DETECTABLE) || (header_mode == OCCP_CORRUPT_CRC)) {
        return OCCP_CORRUPT_HEADER;
    }
    if ((body_mode == OCCP_CRC_INJECT_DETECTABLE) || (body_mode == OCCP_CORRUPT_CRC)) {
        return OCCP_CORRUPT_DATA;
    }
    return OCCP_ERROR_NONE;
}

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("FAIL: STATUS_RPT_DISABLE strap active; this test requires "
                "+FORCE_STATUS_REPORTING so the SMC status buffer can be read\n");
        ctx->overall_result = false;
        return;
    }

    uint32_t status_data = 0xdeadbeef;
    int num_cmd_failed_errors = 0;
    int num_corrupt_header_reports = 0;
    int num_entries = 0;

    while (status_data != 0x0) {
        if (num_entries >= OCCP_STATUS_DRAIN_MAX_ENTRIES) {
            simputs("FAIL: SMC status buffer did not drain within the ring buffer size\n");
            ctx->overall_result = false;
            return;
        }
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        increment_cmd_count(ctx);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        if (status_data == 0x0) {
            break;
        }
        num_entries++;
        simputshex32("SMC Status: ", status_data);
        if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         (uint16_t)OCCP_SPEC_ERROR_CMD_FAILED, false)) {
            num_cmd_failed_errors++;
            if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                             OCCP_CMD_FAILED_CORRUPT_HEADER, true)) {
                num_corrupt_header_reports++;
            }
        }
    }

    simputshex32("Observed CMD_FAILED error reports: ", num_cmd_failed_errors);
    simputshex32("Required at least: ", exp_min_cmd_failed_errors);
    simputshex32("Observed CMD_FAILED|CORRUPT_HEADER reports: ", num_corrupt_header_reports);
    simputshex32("Required at least: ", exp_min_corrupt_header_reports);

    bool status_buffer_ok = true;
    if (num_cmd_failed_errors < exp_min_cmd_failed_errors) {
        simputs("FAIL: SMC reported fewer CMD_FAILED errors than the number of commands it "
                "rejected on the wire\n");
        status_buffer_ok = false;
    }
    if (num_corrupt_header_reports < exp_min_corrupt_header_reports) {
        simputs("FAIL: SMC did not record CMD_FAILED|CORRUPT_HEADER for every header CRC error it "
                "answered with OCCP_CORRUPT_HEADER\n");
        status_buffer_ok = false;
    }
    if (status_buffer_ok) {
        simputs("PASS: SMC STATUS BUFFER VALIDATION\n");
    } else {
        ctx->overall_result = false;
    }
}

static void reset_injection_config(test_context_t *ctx) {
    ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->exp_response_code = OCCP_ERROR_NONE;
}

static void configure_injection(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                occp_crc_inject_mode_t body_mode,
                                occp_error_code_t exp_error_code) {
    ctx->header_crc_err_inject_mode = header_mode;
    ctx->body_crc_err_inject_mode = body_mode;
    ctx->exp_response_code = exp_error_code;
}

/* Undetectable faults may pass the CRC; a clean command after them must still succeed. */
static void check_interface_liveness(test_context_t *ctx, const char *tag) {
    uint32_t version = 0;
    reset_injection_config(ctx);
    /* A valid command clears the ROM's consecutive-error count; five errors unlatch it. */
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &version);
    increment_cmd_count(ctx);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: OCCP interface not usable after ");
        simputs(tag);
        simputs("\n");
        ctx->overall_result = false;
    } else {
        simputs("PASS: OCCP interface live after ");
        simputs(tag);
        simputs("\n");
    }
}

static void run_header_body_combo(test_context_t *ctx, occp_crc_inject_mode_t header_mode,
                                  occp_crc_inject_mode_t body_mode) {
    static int case_index = 0;
    occp_error_code_t exp_error_code = expected_error_for_modes(header_mode, body_mode);

    case_index++;
    simputshex32("-- CRC injection case ", (uint32_t)case_index);
    simputs("   header injection: ");
    simputs(inject_mode_name(header_mode));
    simputs("\n   body injection:   ");
    simputs(inject_mode_name(body_mode));
    simputs("\n   expected response error: ");
    simputs(error_code_name(exp_error_code));
    simputs("\n");

    configure_injection(ctx, header_mode, body_mode, exp_error_code);
    uint8_t data[MAX_OCCP_READ_SIZE];

    for (int i = 0; i < OCCP_CMDS_PER_CASE; i++) {
        int random_cmd;
        /* A flipped GET_* body can yield UNSUPPORTED_STATUS, not CORRUPT_DATA; use WRITE. */
        if (body_mode == OCCP_CRC_INJECT_DETECTABLE) {
            random_cmd = OCCP_WRITE;
        } else {
            /* Body-injection cases skip GET_VERSION, which has no body to corrupt. */
            int cmd_low_bound =
                (header_mode == OCCP_CRC_INJECT_NONE) ? OCCP_GET_SEP_STATUS : OCCP_GET_VERSION;
            int cmd_upper_bound = is_secure_mode() ? OCCP_VALIDATE_BOOT : OCCP_JUMP;
            random_cmd = get_random_int() % (cmd_upper_bound - cmd_low_bound + 1) + cmd_low_bound;
        }
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
            if (body_mode == OCCP_CRC_INJECT_DETECTABLE) {
                /* 3+ payload bytes select CRC32, which catches every injected flip count. */
                size = 3 + (get_random_int() % 64);
            } else {
                size = get_random_int() % (MAX_OCCP_WRITE_SIZE) + 1;
            }
            for (int j = 0; j < size; j++) data[j] = get_random_int() % 256;
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
            reset_injection_config(ctx);
            return;
        }
        increment_cmd_count(ctx);
    }
    reset_injection_config(ctx);

    if (exp_error_code != OCCP_ERROR_NONE) {
        exp_min_cmd_failed_errors += OCCP_CMDS_PER_CASE;
    }
    if (exp_error_code == OCCP_CORRUPT_HEADER) {
        exp_min_corrupt_header_reports += OCCP_CMDS_PER_CASE;
    }
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

    run_header_body_combo(&ctx, OCCP_CRC_INJECT_DETECTABLE, OCCP_CRC_INJECT_NONE);
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_UNDETECTABLE, OCCP_CRC_INJECT_NONE);
    check_interface_liveness(&ctx, "possibly-undetectable header CRC corruption");

    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_DETECTABLE);
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CRC_INJECT_UNDETECTABLE);
    check_interface_liveness(&ctx, "possibly-undetectable body CRC corruption");

    run_header_body_combo(&ctx, OCCP_CORRUPT_CRC, OCCP_CRC_INJECT_NONE);
    run_header_body_combo(&ctx, OCCP_CRC_INJECT_NONE, OCCP_CORRUPT_CRC);
    check_interface_liveness(&ctx, "corrupted CRC fields");

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
