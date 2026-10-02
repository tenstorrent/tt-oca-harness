/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Checks that the ROM rejects OCCP READ/WRITE outside the allowed window with Invalid_address,
 * logs one access-denied status record per rejection, and still serves the window itself.
 */

#include "occp_test_common.h"
#include "virt_console.h"
#include <string.h>

static uint32_t expected_read_access_denied = 0;
static uint32_t expected_write_access_denied = 0;

static uint8_t shared_write_buffer[MAX_OCCP_WRITE_SIZE];
static uint8_t shared_read_buffer[MAX_OCCP_READ_SIZE];

static void validate_smc_status_buffer_for_secure_access(test_context_t *ctx,
                                                         uint32_t exp_read_denied,
                                                         uint32_t exp_write_denied) {
    simputs("=== Validating SMC Status Buffer for Secure Access Violations ===\n");
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap active; skipping SMC status buffer validation\n");
        return;
    }

    uint32_t smc_status = 0;
    int retval;
    uint32_t total_read_access_denied = 0;
    uint32_t total_write_access_denied = 0;
    uint32_t unexpected_errors = 0;

    while (true) {
        retval = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &smc_status);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to read SMC status\n");
            ctx->overall_result = false;
            break;
        }
        if (smc_status == 0) {
            break;
        }

        simputshex32("SMC Status Entry: 0x", smc_status);
        if (occp_status_matches_expected(smc_status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                         (uint16_t)OCCP_SPEC_ERROR_READ_ACCESS_DENIED, false)) {
            total_read_access_denied++;
        } else if (occp_status_matches_expected(
                       smc_status, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                       (uint16_t)OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED, false)) {
            total_write_access_denied++;
        } else if (occp_status_matches_expected(smc_status, OCCP_FW_ID_SMC_BL0,
                                                OCCP_STATUS_MSG_ERROR,
                                                (uint16_t)OCCP_SPEC_ERROR_CMD_FAILED, false)) {
            // Command-failed records are tolerated and not counted.
        } else if (occp_is_smc_error_code(smc_status)) {
            uint16_t msg_value = OCCP_STATUS_EXTRACT_VALUE(smc_status);
            if (msg_value != 0) {
                unexpected_errors++;
            }
        }
    }

    simputshex32("Total READ access denied errors: ", total_read_access_denied);
    simputshex32("Total WRITE access denied errors: ", total_write_access_denied);
    simputshex32("Total unexpected errors: ", unexpected_errors);

    if (total_read_access_denied != exp_read_denied) {
        simputshex32("FAIL: READ access denied count mismatch (expected: ", exp_read_denied);
        simputshex32(", actual: ", total_read_access_denied);
        ctx->overall_result = false;
    }
    if (total_write_access_denied != exp_write_denied) {
        simputshex32("FAIL: WRITE access denied count mismatch (expected: ", exp_write_denied);
        simputshex32(", actual: ", total_write_access_denied);
        ctx->overall_result = false;
    }
    if (unexpected_errors != 0) {
        simputshex32("FAIL: Unexpected error entries found in SMC status buffer: ",
                     unexpected_errors);
        ctx->overall_result = false;
    } else if (ctx->overall_result) {
        simputs("PASS: SMC status buffer matches expected secure access violation counts\n");
    }
}

#define INVALID_ADDR_BELOW_START 0xC0000000ULL
#define INVALID_ADDR_ABOVE_END 0xC0200000ULL

#define NUM_RANDOM_OPERATIONS 2
#define NUM_VALID_CONTROL_OPS 2

static uint64_t generate_random_invalid_address_below(void) {
    uint64_t range = OCCP_TEST_BASE_ADDR - INVALID_ADDR_BELOW_START;
    uint32_t offset = get_random_int() % range;
    return (INVALID_ADDR_BELOW_START + offset) & 0xfffffffc;
}

static uint64_t generate_random_invalid_address_above(void) {
    uint64_t range = INVALID_ADDR_ABOVE_END - OCCP_TEST_UPPER_ADDR;
    uint32_t offset = get_random_int() % range;
    return (OCCP_TEST_UPPER_ADDR + offset) & 0xfffffffc;
}

static uint64_t generate_random_invalid_address(void) {
    if (get_random_int() % 2) {
        return generate_random_invalid_address_below();
    } else {
        return generate_random_invalid_address_above();
    }
}

// In unsecure mode only the protected range below the OCCP window is rejected.
static uint64_t generate_random_invalid_address_unsecure_mode(void) {
    uint64_t range = OCCP_TEST_BASE_ADDR - SMC_SRAM_BASE_ADDR;
    uint32_t offset = get_random_int() % range;
    return (SMC_SRAM_BASE_ADDR + offset) & 0xfffffffc;
}

static void send_invalid_occp_write(test_context_t *ctx) {
    uint16_t len = get_random_occp_write_size();
    uint64_t test_addr = is_secure_mode() ? generate_random_invalid_address()
                                          : generate_random_invalid_address_unsecure_mode();

    for (int j = 0; j < len; j++) {
        shared_write_buffer[j] = get_random_int() & 0xFF;
    }

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int retval = occp_send_write_command(ctx, ctx->slave_addr, test_addr, shared_write_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (retval != OCCP_SUCCESS) {
        simputs("WRITE FAIL: OCCP command send failed\n");
        ctx->overall_result = false;
    } else {
        simputs("WRITE command sent\n");
    }
    expected_write_access_denied++;
}

static void send_invalid_occp_read(test_context_t *ctx) {
    uint16_t len = get_random_occp_read_size();
    uint64_t test_addr = is_secure_mode() ? generate_random_invalid_address()
                                          : generate_random_invalid_address_unsecure_mode();

    memset(shared_read_buffer, 0xAA, sizeof(shared_read_buffer));

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int retval = occp_send_read_command(ctx, ctx->slave_addr, test_addr, shared_read_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (retval == OCCP_SUCCESS) {
        simputs("READ PASS: Security violation correctly detected by command return value\n");
    } else {
        simputs("READ FAIL: Command failed\n");
        ctx->overall_result = false;
    }
    expected_read_access_denied++;
}

static void execute_random_invalid_operations(test_context_t *ctx, int num_operations) {
    for (int i = 0; i < num_operations; i++) {
        uint8_t is_read = get_random_int() % 2;

        if (is_read) {
            send_invalid_occp_read(ctx);
        } else {
            send_invalid_occp_write(ctx);
        }
    }
}

static void test_boundary_cases(test_context_t *ctx) {

    simputs("\n=== Testing Boundary Cases ===\n");

    uint16_t len = get_random_occp_write_size();

    for (int j = 0; j < len; j++) {
        shared_write_buffer[j] = get_random_int() & 0xFF;
    }

    uint64_t random_offset_below = get_random_int() % 0x20;
    uint64_t addr_below = (OCCP_TEST_BASE_ADDR - 1 - random_offset_below) & 0xfffffffc;
    simputshex32("Boundary test: Address just below range (0x", addr_below);
    simputshex32(" offset: ", random_offset_below);

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_below, shared_write_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("WRITE command sent\n");
    }
    expected_write_access_denied++;

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int read_result =
        occp_send_read_command(ctx, ctx->slave_addr, addr_below, shared_read_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (read_result == OCCP_SUCCESS) {
        simputs("  READ PASS: Security violation detected\n");
    } else {
        simputs("READ command failed\n");
        ctx->overall_result = false;
    }
    expected_read_access_denied++;

    // Addresses above the window are valid in unsecure mode.
    if (is_secure_mode()) {
        uint64_t random_offset_above = get_random_int() % 0x20;
        uint64_t addr_above = (OCCP_TEST_UPPER_ADDR + random_offset_above) & 0xfffffffc;
        simputshex32("Boundary test: Address at/above upper boundary (0x", addr_above);
        simputshex32(" offset: ", random_offset_above);

        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        write_result =
            occp_send_write_command(ctx, ctx->slave_addr, addr_above, shared_write_buffer, len);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;

        if (write_result != OCCP_SUCCESS) {
            simputs("WRITE command failed\n");
            ctx->overall_result = false;
        } else {
            simputs("WRITE command sent\n");
        }
        expected_write_access_denied++;

        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_above, shared_read_buffer, len);
        increment_cmd_count(ctx);
        ctx->exp_response_code = OCCP_ERROR_NONE;

        if (read_result == OCCP_SUCCESS) {
            simputs("  READ PASS: Security violation detected\n");
        } else {
            simputs("READ command failed\n");
            ctx->overall_result = false;
        }
        expected_read_access_denied++;
    }

    // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    uint64_t addr_sram_base = SMC_SRAM_BASE_ADDR;
    simputshex32("Boundary test: Address at SRAM base (0x", addr_sram_base);
    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_sram_base, shared_write_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Security violation detected...\n");
    }
    expected_write_access_denied++;

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    read_result =
        occp_send_read_command(ctx, ctx->slave_addr, addr_sram_base, shared_read_buffer, len);
    increment_cmd_count(ctx);
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (read_result == OCCP_SUCCESS) {
        simputs("  READ PASS: Security violation detected\n");
    } else {
        simputs("READ command failed\n");
        ctx->overall_result = false;
    }
    expected_read_access_denied++;

    uint64_t random_offset_start = (get_random_int() % 0x20) & 0xfffffffc;
    uint64_t addr_valid_start = OCCP_TEST_BASE_ADDR + random_offset_start;
    simputshex32("Boundary test: Valid address at start of range (0x", addr_valid_start);
    simputshex32(" offset: ", random_offset_start);

    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_valid_start, shared_write_buffer, len);
    increment_cmd_count(ctx);

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Valid boundary address write succeeded\n");

        memset(shared_read_buffer, 0x00, sizeof(shared_read_buffer));
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_valid_start, shared_read_buffer, len);
        increment_cmd_count(ctx);

        if (read_result != OCCP_SUCCESS) {
            simputshex32("  READ FAIL: Expected success for valid address, got error ",
                         read_result);
            ctx->overall_result = false;
        } else if (memcmp(shared_write_buffer, shared_read_buffer, len) == 0) {
            simputs("  READ PASS: Valid boundary address read succeeded with correct data\n");
        } else {
            simputs("  READ FAIL: Data mismatch on valid boundary readback\n");
            ctx->overall_result = false;
        }
    }

    uint64_t random_offset_end = get_random_int() % 0x20;
    uint64_t addr_valid_end = (OCCP_TEST_UPPER_ADDR - 8 - len - random_offset_end) & 0xfffffffc;
    simputshex32("Boundary test: Valid address near end of range (0x", addr_valid_end);
    simputshex32(" offset: ", random_offset_end);

    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_valid_end, shared_write_buffer, len);
    increment_cmd_count(ctx);

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Valid boundary address write succeeded\n");

        memset(shared_read_buffer, 0x00, sizeof(shared_read_buffer));
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_valid_end, shared_read_buffer, len);
        increment_cmd_count(ctx);

        if (read_result != OCCP_SUCCESS) {
            simputs("READ command failed\n");
            ctx->overall_result = false;
        } else if (memcmp(shared_write_buffer, shared_read_buffer, len) == 0) {
            simputs("  READ PASS: Valid boundary address read succeeded with correct data\n");
        } else {
            simputs("  READ FAIL: Data mismatch on valid boundary readback\n");
            ctx->overall_result = false;
        }
    }
}

static void run_security_access_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Secure Mode Access Restriction Test ===\n");

    ctx->overall_result = true;
    ctx->cmd_count = 0;
    ctx->exp_occp_last_error = 0;
    expected_read_access_denied = 0;
    expected_write_access_denied = 0;

    test_boundary_cases(ctx);

    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    simputs("\n=== Testing Random Invalid Operations (Interspersed R/W) ===\n");
    execute_random_invalid_operations(ctx, NUM_RANDOM_OPERATIONS);
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    simputs("\n=== Control Test: Valid Operations ===\n");
    ctx->test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx->test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;

    execute_random_commands(ctx, NUM_VALID_CONTROL_OPS);

    validate_smc_status_buffer_for_secure_access(ctx, expected_read_access_denied,
                                                 expected_write_access_denied);
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("\nALL SECURITY ACCESS TESTS PASSED!\n");
        test_pass(0);
    } else {
        simputs("\nSOME SECURITY ACCESS TESTS FAILED!\n");
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
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_security_access_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);
}
