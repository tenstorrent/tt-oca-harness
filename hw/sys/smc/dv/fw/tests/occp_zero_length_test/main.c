/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends zero-length WRITE and READ commands and expects each to draw error code 0x03
 * Invalid_header, latch the internal error OCCP_ERROR_BUFFER_OVERFLOW, and log one
 * WRITE_OVERFLOW or READ_OVERFLOW status record.
 */

#include "occp_test_common.h"
#include "smc_occp_error_codes.h"
#include "smc_status.h"

/* ROM value of OCCP_ERROR_BUFFER_OVERFLOW; its header is not on the DV include path. */
#define OCCP_INTERNAL_ERROR_BUFFER_OVERFLOW 0x06u

static void validate_smc_status_buffer(test_context_t *ctx, int exp_write_errors,
                                       int exp_read_errors) {
    uint32_t smc_status = 0;
    int retval;
    int total_write_errors = 0;
    int total_read_errors = 0;

    simputs("=== Validating SMC Status Buffer ===\n");

    simputs("Reading SMC status buffer entries:\n");

    /* Bound the drain so a target that never returns 0 fails here, not as a run timeout. */
    const int max_iterations = 2 * (exp_write_errors + exp_read_errors) + 64;
    int iterations = 0;

    while (true) {
        if (iterations++ >= max_iterations) {
            simputshex32("FAIL: SMC status drain exceeded bound, iterations: ", iterations);
            simputshex32("      last status word: 0x", smc_status);
            ctx->overall_result = false;
            break;
        }

        retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &smc_status);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to read SMC status\n");
            ctx->overall_result = false;
            break;
        }

        if (smc_status == 0) {
            simputs("SMC status buffer is empty (returned 0)\n");
            break;
        }

        increment_cmd_count(ctx);

        uint32_t msg_type = (smc_status >> 24) & 0xFF;
        uint32_t fw_id = (smc_status >> 16) & 0xFF;
        uint32_t msg_value = smc_status & 0xFFFF;

        if (fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
            simputshex32("FAIL: status record from unexpected fw_id: 0x", smc_status);
            ctx->overall_result = false;
            continue;
        }

        if (msg_type != SMC_STATUS_TYPE_ERROR) {
            /* Boot-sequence info and warning records share this buffer. */
            simputshex32("  non-error status record (ignored): 0x", smc_status);
            continue;
        }

        if (msg_value == SMC_OCCP_ERROR_READ_OVERFLOW) {
            simputs("  Found error SMC_OCCP_ERROR_READ_OVERFLOW\n");
            total_read_errors++;
        } else if (msg_value == SMC_OCCP_ERROR_WRITE_OVERFLOW) {
            simputs("  Found error SMC_OCCP_ERROR_WRITE_OVERFLOW\n");
            total_write_errors++;
        } else if (msg_value <= 0xFFF &&
                   SMC_OCCP_ERROR_BASE(msg_value) == SMC_OCCP_ERROR_CMD_FAILED) {
            /* The ROM logs a CMD_FAILED record with the return code for each failed command. */
            simputshex32("  companion SMC_OCCP_ERROR_CMD_FAILED record: 0x", msg_value);
        } else {
            simputshex32("FAIL: Found unknown error: 0x", msg_value);
            ctx->overall_result = false;
        }
    }

    simputs("=== SMC Status Buffer Validation Summary ===\n");
    simputshex32("Total write errors: ", total_write_errors);
    simputshex32("Total read errors: ", total_read_errors);
    simputshex32("Expected write errors: ", exp_write_errors);
    simputshex32("Expected read errors: ", exp_read_errors);
    if (total_write_errors != exp_write_errors || total_read_errors != exp_read_errors) {
        simputs("FAIL: SMC STATUS BUFFER VALIDATION: FAIL\n");
        ctx->overall_result = false;
    }
}

static void check_occp_last_error(test_context_t *ctx) {
    uint32_t status = 0;

    simputs("=== Checking latched OCCP internal error code ===\n");

    int retval = occp_send_get_occp_error_code_command(ctx, ctx->slave_addr, &status);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: could not read the OCCP internal error code\n");
        ctx->overall_result = false;
        return;
    }

    uint32_t last_error = status & 0xFF;
    uint32_t expected = (uint32_t)ctx->exp_occp_last_error;
    simputshex32("OCCP internal error code: 0x", last_error);
    if (last_error != expected) {
        simputshex32("FAIL: expected OCCP internal error code: 0x", expected);
        ctx->overall_result = false;
    }
}

static void test_zero_length_write(test_context_t *ctx, uint64_t addr) {
    int result;
    uint8_t dummy_data = 0;

    simputshex64("=== Testing Zero Length Write at 0x", addr);
    simputs(" ===\n");

    /* Pinning the code makes a timeout, CRC failure or other error code fail the command. */
    ctx->exp_occp_last_error = OCCP_INTERNAL_ERROR_BUFFER_OVERFLOW;
    ctx->exp_response_code = OCCP_INVALID_HEADER;
    // needs to be 8-byte aligned
    result =
        occp_send_write_command(ctx, ctx->slave_addr, addr & 0xfffffffffffffff8ULL, &dummy_data, 0);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (result == OCCP_SUCCESS) {
        simputs("received expected OCCP_INVALID_HEADER on zero-length write\n");
    } else {
        ctx->overall_result = false;
        simputs("FAIL: zero-length write did not draw the expected OCCP_INVALID_HEADER\n");
    }
}

static void test_zero_length_read(test_context_t *ctx, uint64_t addr) {
    int result;
    uint8_t dummy_buffer[1] = {0};

    simputshex64("=== Testing Zero Length Read at 0x", addr);
    simputs(" ===\n");

    ctx->exp_occp_last_error = OCCP_INTERNAL_ERROR_BUFFER_OVERFLOW;
    ctx->exp_response_code = OCCP_INVALID_HEADER;
    // needs to be 8-byte aligned
    result =
        occp_send_read_command(ctx, ctx->slave_addr, addr & 0xfffffffffffffff8ULL, dummy_buffer, 0);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (result == OCCP_SUCCESS) {
        simputs("received expected OCCP_INVALID_HEADER on zero-length read\n");
    } else {
        ctx->overall_result = false;
        simputs("FAIL: zero-length read did not draw the expected OCCP_INVALID_HEADER\n");
    }
}

static void run_zero_length_tests(test_context_t *ctx) {
    simputs("=== Zero Length Operations Test ===\n\n");

    int num_write_errors = 0;
    int num_read_errors = 0;

    test_zero_length_write(ctx, ctx->test_base_addr);
    test_zero_length_read(ctx, ctx->test_base_addr);
    num_write_errors++;
    num_read_errors++;

    test_zero_length_write(ctx, ctx->test_upper_addr_bound - 1);
    test_zero_length_read(ctx, ctx->test_upper_addr_bound - 1);
    num_write_errors++;
    num_read_errors++;

    simputs("=== Testing Random Zero Length Operations ===\n");
    for (int i = 0; i < 10; i++) {
        if (get_random_int() % 2) {
            test_zero_length_write(
                ctx, ctx->test_base_addr +
                         (get_random_int() % (ctx->test_upper_addr_bound - ctx->test_base_addr)));
            num_write_errors++;
        } else {
            test_zero_length_read(
                ctx, ctx->test_base_addr +
                         (get_random_int() % (ctx->test_upper_addr_bound - ctx->test_base_addr)));
            num_read_errors++;
        }
    }
    /* Sample the latched error code before the status drain adds its own traffic. */
    check_occp_last_error(ctx);

    validate_smc_status_buffer(ctx, num_write_errors, num_read_errors);
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        test_pass(0);
    } else {
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    simputs("=== First execute random commands (5 commands) ===\n");
    execute_random_commands(&test_ctx, 5);

    run_zero_length_tests(&test_ctx);

    simputs("=== Second execute random commands (5 commands) ===\n");
    execute_random_commands(&test_ctx, 5);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
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
