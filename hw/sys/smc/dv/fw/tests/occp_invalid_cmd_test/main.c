/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends OCCP requests with an invalid MsgID, an invalid AppID, and both, and checks that the
 * ROM rejects each and records the expected entries in the SMC status buffer.
 * Requires +FORCE_STATUS_REPORTING; an active STATUS_RPT_DISABLE strap fails the run.
 */

#include "occp_test_common.h"
#include "smc_test.h"
#include <string.h>

int exp_num_rejected_headers = 0;

#define OCCP_STATUS_CMD_FAILED_INVALID_CMD 0x111u
#define OCCP_STATUS_ENTRIES_PER_REJECTION 2

/* The rejected ID is random and not reported back, so only the entry shape is checked. */
static bool is_expected_dispatch_reject_entry(uint16_t value) {
    return ((value & 0xFF00u) == 0x0100u) && ((value & 0x1u) != 0u);
}

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("FAIL: STATUS_RPT_DISABLE strap active; SMC status buffer cannot be read\n");
        simputs("FAIL: this test requires +FORCE_STATUS_REPORTING to pin the strap to 0\n");
        ctx->overall_result = false;
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_reject_entries = 0;
    int num_cmd_failed_entries = 0;
    int num_unexpected_errors = 0;

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
            break;
        }
        uint8_t msg_type = (uint8_t)((status_data >> 24) & 0xFF);
        uint8_t fw_id = (uint8_t)((status_data >> 16) & 0xFF);
        uint16_t value = (uint16_t)(status_data & 0xFFFF);
        if (msg_type != (uint8_t)OCCP_STATUS_MSG_ERROR || fw_id != (uint8_t)OCCP_FW_ID_SMC_BL0) {
            continue;
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
    /* A CMD_UNKNOWN entry for a random ID with low byte 0x10 or 0x11 also reads 0x111. */
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

    simputs("=== Valid Commands Test (baseline) ===\n");
    execute_random_commands(ctx, 1);

    simputs("=== Invalid Header Format Tests (AppID/MsgID) ===\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_MSGID;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_BOTH;
    execute_random_commands(ctx, 1);
    exp_num_rejected_headers += 1;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);
    simputs("Invalid header tests completed\n");

    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    execute_random_commands(ctx, 1);
}

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

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_test_suite(&test_ctx);

    read_and_validate_smc_status_buffer(&test_ctx);

    finalize_test_results(&test_ctx);
}
