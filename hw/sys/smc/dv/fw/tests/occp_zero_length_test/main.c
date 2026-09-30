/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Zero Length Operations Test
 *
 * This test exercises zero length write and read operations to understand
 * the expected behavior and observe OCCP status responses.
 *
 * Test Cases:
 * 1. Zero length write operations at various addresses
 * 2. Zero length read operations at various addresses
 * 3. Status monitoring after each operation
 * 4. Error code analysis
 */

#include "occp_test_common.h"

static void validate_smc_status_buffer(test_context_t *ctx, int exp_write_errors,
                                       int exp_read_errors) {
    uint32_t smc_status = 0;
    int retval;
    int total_write_errors = 0;
    int total_read_errors = 0;

    simputs("=== Validating SMC Status Buffer ===\n");

    simputs("Reading SMC status buffer entries:\n");

    while (true) {
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

        // If we get 0, the buffer is empty
        if (smc_status == 0) {
            simputs("SMC status buffer is empty (returned 0)\n");
            break;
        }

        // Parse status message according to ROM specification:
        // [31:28] - Firmware ID (0x2: SMC BL0)
        // [27:24] - Message Type (0x2: error)
        // [23:0]  - Message Value (OCCP error code)
        uint32_t fw_id = (smc_status >> 28) & 0xF;
        uint32_t msg_type = (smc_status >> 24) & 0xF;
        uint32_t msg_value = smc_status & 0xFFFFFF;

        // Check if this is an SMC ROM error about unknown OCCP command
        if (fw_id == 0x2 && msg_type == 0x2) { // SMC BL0, Error type
            if (msg_value == 0x120) {          // SMC_OCCP_ERROR_READ_OVERFLOW
                simputs("  Found error SMC_OCCP_ERROR_READ_OVERFLOW\n");
                total_read_errors++;
            } else if (msg_value == 0x130) { // SMC_OCCP_ERROR_WRITE_OVERFLOW
                simputs("  Found error SMC_OCCP_ERROR_WRITE_OVERFLOW\n");
                total_write_errors++;
                // we can ignore cmd failed errors, but don't expect any others
            } else if ((msg_value & 0xFF0) != 0x110) { // SMC_OCCP_ERROR_CMD_FAILED
                simputshex32("FAIL: Found unknown error: 0x", msg_value);
                ctx->overall_result = false;
            }
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

static void test_zero_length_write(test_context_t *ctx, uint64_t addr) {
    int result;
    uint8_t dummy_data = 0;

    simputshex32("=== Testing Zero Length Write at 0x", addr);
    simputs(" ===\n");

    // needs to be 8-byte aligned
    result = occp_send_write_command(ctx, ctx->slave_addr, addr & 0xfffffff8, &dummy_data, 0);
    if (result == OCCP_SUCCESS) {
        simputs("received success on zero-length write as expected\n");
    } else {
        ctx->overall_result = false;
        simputs("FAIL: received unexpected error on zero-length write\n");
    }
    ctx->exp_occp_last_error = 0x6;
}

static void test_zero_length_read(test_context_t *ctx, uint64_t addr) {
    int result;
    uint8_t dummy_buffer[1] = {0};

    simputshex32("=== Testing Zero Length Read at 0x", addr);
    simputs(" ===\n");

    simputshex64("Address: 0x", addr);

    // needs to be 8-byte aligned
    result = occp_send_read_command(ctx, ctx->slave_addr, addr & 0xfffffff8, dummy_buffer, 0);
    if (result == OCCP_SUCCESS) {
        ctx->overall_result = false;
        simputs("FAIL: received unexpected success on zero-length read\n");
    } else {
        simputs("received error on zero-length read as expected\n");
    }
    ctx->exp_occp_last_error = 0x6;
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
