/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Checks that the ROM rejects READ, WRITE, VALIDATE_BOOT and JUMP at addresses that are not
 * 4-byte aligned with Invalid_address and logs one matching status record per rejection. JUMP
 * runs only in unsecure mode.
 */

#include "occp_test_common.h"

static int exp_num_read_access_denied = 0;
static int exp_num_write_access_denied = 0;
static int exp_num_validate_addr_failed = 0;
static int exp_num_jump_read_failed = 0;

static void read_and_validate_smc_status_buffer(test_context_t *ctx) {
    simputs("=== Reading and validating SMC status buffer ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }
    uint32_t status_data = 0xdeadbeef;
    int num_read_access_denied = 0;
    int num_write_access_denied = 0;
    int num_validate_addr_failed = 0;
    int num_jump_read_failed = 0;
    while (status_data != 0x0) {
        int retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to get SMC status\n");
            ctx->overall_result = false;
            return;
        }
        simputshex32("SMC Status: ", status_data);
        if (occp_status_matches_expected(status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         (uint16_t)OCCP_SPEC_ERROR_READ_ACCESS_DENIED, false)) {
            num_read_access_denied++;
        } else if (occp_status_matches_expected(
                       status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                       (uint16_t)OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED, false)) {
            num_write_access_denied++;
        } else if (occp_status_matches_expected(
                       status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                       (uint16_t)OCCP_SPEC_ERROR_VALIDATE_ADDRESS_FAILED, false)) {
            num_validate_addr_failed++;
        } else if (occp_status_matches_expected(
                       status_data, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                       (uint16_t)OCCP_SPEC_ERROR_JUMP_READ_FAILED, false)) {
            num_jump_read_failed++;
        }
        increment_cmd_count(ctx);
    }
    simputshex32("Observed READ_ACCESS_DENIED: ", num_read_access_denied);
    simputshex32("Observed WRITE_ACCESS_DENIED: ", num_write_access_denied);
    simputshex32("Observed VALIDATE_ADDRESS_FAILED: ", num_validate_addr_failed);
    simputshex32("Observed JUMP_READ_FAILED: ", num_jump_read_failed);
    if (num_read_access_denied != exp_num_read_access_denied ||
        num_write_access_denied != exp_num_write_access_denied ||
        num_validate_addr_failed != exp_num_validate_addr_failed ||
        num_jump_read_failed != exp_num_jump_read_failed) {
        simputs("FAIL: SMC STATUS BUFFER VALIDATION: FAIL\n");
        ctx->overall_result = false;
    } else {
        simputs("PASS: SMC STATUS BUFFER VALIDATION\n");
    }
}

static void test_unaligned_write(test_context_t *ctx) {
    uint8_t data[MAX_OCCP_WRITE_SIZE];
    uint64_t upper = ctx->test_upper_addr_bound;
    for (unsigned i = 0; i < 4; i++) {
        uint16_t len = get_random_occp_write_size();
        for (uint16_t j = 0; j < len; j++) {
            data[j] = (uint8_t)(get_random_int() & 0xFF);
        }
        uint64_t range = (upper - ctx->test_base_addr);
        uint64_t max_start = (range > len) ? (range - len) : 0;
        uint64_t offset = (max_start > 0) ? (get_random_int() % (max_start + 1ULL)) : 0;
        uint64_t addr = ctx->test_base_addr + offset;
        if ((addr & 3ULL) == 0ULL) {
            addr += ((get_random_int() % 3U) + 1U);
        }
        if (addr + len > upper) {
            uint64_t over = (addr + len) - upper;
            addr = (addr > over) ? (addr - over) : ctx->test_base_addr;
            if ((addr & 3ULL) == 0ULL)
                addr = (addr + 1ULL <= upper) ? (addr + 1ULL) : (addr - 1ULL);
        }
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        int rc = occp_send_write_command(ctx, ctx->slave_addr, addr, data, len);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;
        if (rc != OCCP_SUCCESS) ctx->overall_result = false;
    }
    exp_num_write_access_denied += 4;
}

static void test_unaligned_read(test_context_t *ctx) {
    uint8_t buf[MAX_OCCP_READ_SIZE];
    uint64_t upper = ctx->test_upper_addr_bound;
    for (unsigned i = 0; i < 4; i++) {
        uint16_t len = (get_random_int() % 16) + 1;
        uint64_t range = (upper - ctx->test_base_addr);
        uint64_t max_start = (range > len) ? (range - len) : 0;
        uint64_t offset = (max_start > 0) ? (get_random_int() % (max_start + 1ULL)) : 0;
        uint64_t addr = ctx->test_base_addr + offset;
        if ((addr & 3ULL) == 0ULL) {
            addr += ((get_random_int() % 3U) + 1U);
        }
        if (addr + len > upper) {
            uint64_t over = (addr + len) - upper;
            addr = (addr > over) ? (addr - over) : ctx->test_base_addr;
            if ((addr & 3ULL) == 0ULL)
                addr = (addr + 1ULL <= upper) ? (addr + 1ULL) : (addr - 1ULL);
        }
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        int rc = occp_send_read_command(ctx, ctx->slave_addr, addr, buf, len);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;
        if (rc != OCCP_SUCCESS) ctx->overall_result = false;
    }
    exp_num_read_access_denied += 4;
}

static void test_unaligned_jump(test_context_t *ctx) {
    uint64_t upper = ctx->test_upper_addr_bound;
    for (unsigned i = 0; i < 4; i++) {
        uint16_t len = 8;
        uint64_t range = (upper - ctx->test_base_addr);
        uint64_t max_start = (range > len) ? (range - len) : 0;
        uint64_t offset = (max_start > 0) ? (get_random_int() % (max_start + 1ULL)) : 0;
        uint64_t addr = ctx->test_base_addr + offset;
        if ((addr & 3ULL) == 0ULL) {
            addr += ((get_random_int() % 3U) + 1U);
        }
        if (addr + len > upper) {
            uint64_t over = (addr + len) - upper;
            addr = (addr > over) ? (addr - over) : ctx->test_base_addr;
            if ((addr & 3ULL) == 0ULL)
                addr = (addr + 1ULL <= upper) ? (addr + 1ULL) : (addr - 1ULL);
        }
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        int rc = occp_send_jump_command(ctx, ctx->slave_addr, addr);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;
        if (rc != OCCP_SUCCESS) ctx->overall_result = false;
    }
    exp_num_jump_read_failed += 4;
}

static void test_unaligned_validate_boot(test_context_t *ctx) {
    uint64_t upper = ctx->test_upper_addr_bound;
    for (unsigned i = 0; i < 4; i++) {
        uint16_t len = 8;
        uint64_t range = (upper - ctx->test_base_addr);
        uint64_t max_start = (range > len) ? (range - len) : 0;
        uint64_t offset = (max_start > 0) ? (get_random_int() % (max_start + 1ULL)) : 0;
        uint64_t addr = ctx->test_base_addr + offset;
        if ((addr & 3ULL) == 0ULL) {
            addr += ((get_random_int() % 3U) + 1U);
        }
        if (addr + len > upper) {
            uint64_t over = (addr + len) - upper;
            addr = (addr > over) ? (addr - over) : ctx->test_base_addr;
            if ((addr & 3ULL) == 0ULL)
                addr = (addr + 1ULL <= upper) ? (addr + 1ULL) : (addr - 1ULL);
        }
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        int rc = occp_send_validate_boot_command(ctx, ctx->slave_addr, addr);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;
        if (rc != OCCP_SUCCESS) ctx->overall_result = false;
    }
    exp_num_validate_addr_failed += 4;
}

static void finalize_test_results(bool overall_pass) {
    if (overall_pass) {
        simputs("ALL TESTS PASSED!\n");
        test_pass(0);
    } else {
        simputs("SOME TESTS FAILED!\n");
        test_fail(0);
    }
}

int main(void) {
    static test_context_t ctx = {0};

    init_test(0);
    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    ctx.overall_result = true;
    ctx.cmd_count = 0;
    ctx.exp_occp_last_error = 0;

    simputs("=== Valid OCCP commands before unaligned tests ===\n");
    execute_random_commands(&ctx, 1);
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    test_unaligned_write(&ctx);
    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    test_unaligned_read(&ctx);
    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    test_unaligned_validate_boot(&ctx);
    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    if (!is_secure_mode()) test_unaligned_jump(&ctx);
    retval = occp_send_get_version_command(&ctx, ctx.slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx.overall_result = false;
    }
    increment_cmd_count(&ctx);
    read_and_validate_smc_status_buffer(&ctx);

    simputs("=== Valid OCCP commands after unaligned tests ===\n");
    execute_random_commands(&ctx, 1);

    finalize_test_results(ctx.overall_result);
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
