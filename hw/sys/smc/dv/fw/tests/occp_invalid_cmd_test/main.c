/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Invalid Command Code Test
 *
 * This test sends commands with invalid OCCP command codes to verify
 * that the ROM properly rejects them and reports appropriate error status.
 *
 * The ROM status buffer preserves only the low byte of an invalid command
 * (SMC_OCCP_ERROR_WITH_DATA): a multi-byte command such as 0xDEAD is stored as
 * 0x101 | 0xAD = 0x1AD.
 */

#include "occp_test_common.h"
#include "smc_test.h"
#include <string.h>

/* Number of headers this run injected and expects the ROM to have rejected. */
int exp_num_rejected_headers = 0;

/*
 * Expected SMC ring-buffer entries per rejected header, derived from
 * hw/sys/smc/bootrom/prod/doc/status-coordination.adoc, section
 * "OCCP ring-buffer status values" (0x101 / 0x110 rows) and the paragraph that
 * follows the table:
 *
 *   1. The command dispatcher reports SMC_OCCP_ERROR_CMD_UNKNOWN (0x101) OR'd
 *      with the low byte of the rejected AppID (invalid-AppID case, which also
 *      takes precedence when both fields are invalid) or of the rejected MsgID
 *      (invalid-MsgID case).  Because the base has bit 0 set, this entry is
 *      always an odd value in 0x101..0x1FF.
 *
 *   2. "After most handlers return an error, the loop emits a second
 *      SMC_OCCP_ERROR_CMD_FAILED value with the returned internal error code."
 *      For a rejected header that handler is the error-response handler, whose
 *      returned internal code is OCCP_ERROR_INVALID_COMMAND (0x01), so this
 *      entry is exactly 0x110 | 0x01 == 0x111 for all three injected cases.
 *
 * So a rejection contributes exactly two entries, and the second one has a
 * fully determined value.  The rejected AppID/MsgID is drawn at random inside
 * occp_send_invalid_header_command() and is not reported back to the test, so
 * entry (1) can only be checked for its shape; entry (2) is checked exactly.
 * Any other SMC error class in the drained buffer (CMD_READ 0x100,
 * READ/WRITE_OVERFLOW 0x120/0x130, access-denied with a detail nibble,
 * VALIDATE_* 0x140/0x141, JUMP_* 0x201/0x202, ...) is not expected on this
 * test's traffic and fails the run.
 */
#define OCCP_STATUS_CMD_FAILED_INVALID_CMD 0x111u
#define OCCP_STATUS_ENTRIES_PER_REJECTION 2

static bool is_expected_dispatch_reject_entry(uint16_t value) {
    /* 0x101 | rejected_id, and 0x110 | OCCP_ERROR_INVALID_COMMAND: both live in
     * the 0x1xx command-dispatch family and both have bit 0 set. */
    return ((value & 0xFF00u) == 0x0100u) && ((value & 0x1u) != 0u);
}

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        /* The testlist entries for this test pass +FORCE_STATUS_REPORTING, which pins
         * STATUS_RPT_DISABLE to 0.  If the strap is set anyway, the ROM rejects OCCP
         * GetStatus and the status buffer -- the only evidence for this test's second
         * claim, "reports appropriate error status" -- cannot be read at all.  That is a
         * loss of the checker, not a passing condition, so the run must not report PASS. */
        simputs("FAIL: STATUS_RPT_DISABLE strap active; SMC status buffer cannot be read\n");
        simputs("FAIL: this test requires +FORCE_STATUS_REPORTING to pin the strap to 0\n");
        ctx->overall_result = false;
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_reject_entries = 0;     /* 0x101|id and 0x111 entries */
    int num_cmd_failed_entries = 0; /* exactly 0x111 */
    int num_unexpected_errors = 0;  /* any other SMC BL0 error entry */

    int exp_num_reject_entries = exp_num_rejected_headers * OCCP_STATUS_ENTRIES_PER_REJECTION;

    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        simputshex32("SMC Status: ", status_data);
        if (status_data == 0x0) {
            break; /* buffer drained */
        }
        /* [31:24] = msg_type, [23:16] = fw_id, [15:0] = status value */
        uint8_t msg_type = (uint8_t)((status_data >> 24) & 0xFF);
        uint8_t fw_id = (uint8_t)((status_data >> 16) & 0xFF);
        uint16_t value = (uint16_t)(status_data & 0xFFFF);
        if (msg_type != (uint8_t)OCCP_STATUS_MSG_ERROR || fw_id != (uint8_t)OCCP_FW_ID_SMC_BL0) {
            continue; /* boot status / warning entries are not this checker's business */
        }
        if (is_expected_dispatch_reject_entry(value)) {
            num_reject_entries++;
            if (value == OCCP_STATUS_CMD_FAILED_INVALID_CMD) {
                num_cmd_failed_entries++;
            }
        } else {
            simputshex32("FAIL: unexpected SMC error class in status buffer: ", status_data);
            num_unexpected_errors++;
        }
    }

    bool buffer_ok = true;
    if (num_unexpected_errors != 0) {
        simputshex32("FAIL: unexpected SMC error entries: ", num_unexpected_errors);
        buffer_ok = false;
    }
    if (num_reject_entries != exp_num_reject_entries) {
        simputshex32("FAIL: Expected ", exp_num_reject_entries);
        simputshex32(" header-rejection status entries, got ", num_reject_entries);
        buffer_ok = false;
    }
    /* One 0x111 per rejected header is mandatory.  More is still correct: the
     * CMD_UNKNOWN entry of a rejection whose random AppID/MsgID low byte is 0x10
     * or 0x11 also renders as 0x111, which is why this is a floor and not an
     * equality.  The total above is an equality and pins the overall count. */
    if (num_cmd_failed_entries < exp_num_rejected_headers) {
        simputshex32("FAIL: Expected at least ", exp_num_rejected_headers);
        simputshex32(" CMD_FAILED(INVALID_COMMAND) 0x111 entries, got ", num_cmd_failed_entries);
        buffer_ok = false;
    }
    if (!buffer_ok) {
        ctx->overall_result = false;
        return;
    }
    simputshex32("PASS: ", num_reject_entries);
    simputs(" header-rejection status entries found, no other SMC error class\n");
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Invalid Command Code Test ===\n");

    ctx->overall_result = true;
    int retval;
    uint32_t status_data = 0;

    // Execute a few valid commands first to establish baseline
    simputs("=== Valid Commands Test (baseline) ===\n");
    execute_random_commands(ctx, 1);

    simputs("=== Invalid Header Format Tests (AppID/MsgID) ===\n");

    // Case 1: Valid AppID (Base) with invalid MsgID -> expect Invalid_MsgID
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_MSGID;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Case 2: Invalid AppID with valid MsgID (0) -> expect Invalid_AppID
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Case 3: Invalid AppID and Invalid MsgID -> expect Invalid_AppID precedence
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_BOTH;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // relatch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    simputs("Invalid header tests completed\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    // recovery from invalid command
    execute_random_commands(ctx, 1);
}

/* test_pass()/test_fail() are noreturn (dv/fw/include/smc_test.h): they publish the
 * verdict on the master-BFM scratch register the cocotb monitor polls, then wfi
 * forever.  Nothing may follow them here: anything after this if/else can never
 * run. */
static __attribute__((noreturn)) void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        test_pass(0);
    } else {
        simputs("SOME TESTS FAILED!\n");
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
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

    // Read and validate the status buffer
    read_and_validate_smc_status_buffer(&test_ctx);

    // Finalize and report results (does not return)
    finalize_test_results(&test_ctx);
}
