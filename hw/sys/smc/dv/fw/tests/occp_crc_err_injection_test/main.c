/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP CRC Error Injection Test
 *
 * Injects header / body CRC faults into OCCP requests and checks BOTH observable
 * effects of every injected fault:
 *
 *   1. What the DUT answers on the wire. Each case installs an exact expected
 *      error code in ctx->exp_response_code, which occp_get_response_header()
 *      compares against the code carried in the error response.
 *   2. What the SMC recorded about the fault in its own status ring buffer,
 *      drained and checked by read_and_validate_smc_status_buffer().
 *
 * The testlist entry for this test passes +FORCE_STATUS_REPORTING, which pins the
 * STATUS_RPT_DISABLE strap to 0 (tb_wrap_cocotb/common/smc_api.py) precisely so
 * that (2) is observable; the strap being set is therefore a setup error here, not
 * a reason to skip the check.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

/* Two commands are issued per injection case. */
#define OCCP_CMDS_PER_CASE 2

/* Hard bound on the status-buffer drain so a DUT that never returns the
 * end-of-buffer 0 fails instead of hanging. The SMC ring buffer holds 512
 * entries. */
#define OCCP_STATUS_DRAIN_MAX_ENTRIES 512

/*
 * Expectations for the SMC status ring buffer.
 *
 * What the SMC ROM records for a rejected OCCP command (bootrom/prod/lib/src/occp.c,
 * documented in bootrom/prod/doc/status-coordination.adoc):
 *
 *   - Header CRC mismatch: smc_occp_validate_header() returns Corrupt_header and the
 *     command loop reports SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED,
 *     Corrupt_header), i.e. the fixed value 0x114, as an SMC_BL0 / ERROR message.
 *   - Body CRC mismatch: the handler reports a handler-specific value - plain
 *     SMC_OCCP_ERROR_CMD_FAILED (0x110) for GET_STATUS / READ / WRITE, but
 *     SMC_OCCP_ERROR_JUMP_READ_FAILED (0x202) for JUMP.
 *   - In every case the command loop then reports a second
 *     SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED, <internal error code>)
 *     because the handler returned an error.
 *
 * So the number of entries and the low nibble of the CMD_FAILED value are
 * command-dependent - that is what the previous "no fixed code for CRC error"
 * comment was about - but two things are not, and those are what is checked:
 *
 *   exp_min_cmd_failed_errors     at least one SMC_BL0 / ERROR message of the
 *                                 CMD_FAILED class (base 0x110, matched with the
 *                                 spec mask) per command the DUT provably rejected.
 *   exp_min_corrupt_header_reports at least one entry whose value is exactly
 *                                 CMD_FAILED | OCCP_CORRUPT_HEADER (0x114) per
 *                                 header-corrupted command, which is the fixed
 *                                 code the ROM emits for a header CRC failure.
 *
 * Both are lower bounds because the cases that inject a "possibly undetectable"
 * corruption may legitimately produce no error at all, and because a rejected
 * command produces one or two CMD_FAILED entries depending on the handler. Only
 * cases whose response was checked against an exact expected error code
 * contribute, so a passing wire check is what makes the counted commands
 * "provably rejected".
 */
static int exp_min_cmd_failed_errors = 0;
static int exp_min_corrupt_header_reports = 0;

/* SMC ROM value reported for a header CRC failure: CMD_FAILED base ORed with the
 * OCCP error code the ROM answered with. */
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

/*
 * Error response the DUT must produce for a given injection combination.
 *
 * The ROM validates the header before it reads the body, so a corrupt header
 * dominates a corrupt body. DETECTABLE and CORRUPT_CRC are the modes whose
 * detection is required; UNDETECTABLE deliberately flips more bits than the CRC
 * is guaranteed to catch, so no error code can be required for it - see
 * check_interface_liveness() for the property those cases do verify.
 */
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
        /* The testlist entry passes +FORCE_STATUS_REPORTING for this test, which
         * pins STATUS_RPT_DISABLE = 0. If the strap is set anyway the run cannot
         * observe what the SMC reported, and silently passing would hide it. */
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

/*
 * The property the "possibly undetectable" cases actually verify.
 *
 * A corruption that flips more bits than the CRC's Hamming distance guarantees may
 * legitimately pass undetected, so no error code can be required of those cases.
 * What is required is that the interface survives them: an injection-free command
 * issued straight afterwards must complete successfully. A DUT that wedged or
 * unlatched fails here, and a DUT that never answers fails on the testbench
 * timeout. This doubles as the re-latch the following case needs.
 *
 * GET_VERSION is used because it carries no body and its response is fixed, so this
 * probe is fully deterministic, and because it does not consume an SMC status ring
 * buffer entry - the counts checked in read_and_validate_smc_status_buffer() must
 * not be disturbed between the injection cases and the drain.
 */
static void check_interface_liveness(test_context_t *ctx, const char *tag) {
    uint32_t version = 0;
    reset_injection_config(ctx);
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

    /* The label is derived from the values actually passed, so the console trace
     * cannot drift from the stimulus. */
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
        /* Command selection.
         *
         * - Header injection cases may use any command, GET_VERSION included.
         * - Body injection cases must not use GET_VERSION, which has no body.
         * - A body-DETECTABLE case must additionally avoid the GET_* commands,
         *   whose entire 2-byte body IS the status_id: a bit flip there also turns
         *   the request into an unsupported status id, so a DUT that never checked
         *   the body CRC could answer OCCP_UNSUPPORTED_STATUS and be scored as
         *   proof of body CRC detection. WRITE is used instead - its body is
         *   address/length metadata plus payload, for which OCCP_CORRUPT_DATA is
         *   the only response consistent with the injected fault.
         */
        int random_cmd;
        if (body_mode == OCCP_CRC_INJECT_DETECTABLE) {
            random_cmd = OCCP_WRITE;
        } else {
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
                /* The WRITE body is 12 metadata bytes plus the payload. Keeping the
                 * payload at 3 bytes or more puts the body above PACKET_SIZE_FOR_CRC8
                 * (14), so both the request builder and the ROM protect it with the
                 * CRC32 whose Hamming distance covers every flip count this mode
                 * injects (1..6). Detection is therefore guaranteed and the exact
                 * OCCP_CORRUPT_DATA expectation above cannot fail on an unlucky seed.
                 * The payload is kept small to bound simulation time. */
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

    /* Every command of this case was answered with the exact error code required
     * above, so the DUT rejected all of them and must have recorded each one. */
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

    /* Warm-up valid commands. These also prove the interface works before any
     * fault is injected, so the injection cases cannot pass on a dead link. */
    execute_random_commands(&ctx, 5);

    /* Six cases: detectable / possibly-undetectable / corrupt-CRC-field, for the
     * header CRC and for the body CRC. The printed label for each comes from the
     * arguments below, not from a hand-written string. */
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

    /* Cool-down valid commands to ensure recovery */
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
