/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Secure Mode Access Restriction Test
 *
 * Tests that in secure mode, the ROM returns appropriate OCCP errors when
 * attempting READ/WRITE operations to addresses outside the allowed range
 * (0xC0066400 to 0xC015FFFF). For invalid reads, also verifies data is all zeros.
 */

#include "occp_test_common.h"
#include "virt_console.h"
#include <string.h>

// Track expected secure access violations observed during the test
static uint32_t expected_read_access_denied = 0;
static uint32_t expected_write_access_denied = 0;

// Shared buffers reused across the test to reduce ROM/BSS footprint
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
    uint32_t total_validate_security_errors = 0;
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
            // ignore CMD_FAILED entries for this test
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

    // Compare against expected counts gathered during the test
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

// Memory range definitions
#define INVALID_ADDR_BELOW_START 0xC0000000ULL // Well below allowed range
#define INVALID_ADDR_ABOVE_END 0xC0200000ULL   // Well above allowed range

// Test configuration
#define NUM_RANDOM_OPERATIONS 2 // Number of random read/write operations
#define NUM_VALID_CONTROL_OPS 2 // Number of valid operations for control

static uint64_t generate_random_invalid_address_below(void) {
    // Generate random address below allowed range (0xC0000000 to 0xC005FFFF)
    uint64_t range = OCCP_TEST_BASE_ADDR - INVALID_ADDR_BELOW_START;
    uint32_t offset = get_random_int() % range;
    return (INVALID_ADDR_BELOW_START + offset) & 0xfffffffc;
}

static uint64_t generate_random_invalid_address_above(void) {
    // Generate random address above allowed range (0xC0160000 to 0xC01FFFFF)
    uint64_t range = INVALID_ADDR_ABOVE_END - OCCP_TEST_UPPER_ADDR;
    uint32_t offset = get_random_int() % range;
    return (OCCP_TEST_UPPER_ADDR + offset) & 0xfffffffc;
}

static uint64_t generate_random_invalid_address(void) {
    // Randomly choose between below or above invalid ranges
    if (get_random_int() % 2) {
        return generate_random_invalid_address_below();
    } else {
        return generate_random_invalid_address_above();
    }
}

// for unsecure mode, only invalid offsets are inside of the protected range (0xc0060000 to
// 0xc0066400)
static uint64_t generate_random_invalid_address_unsecure_mode(void) {
    // Randomly choose between below or above invalid ranges
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
    increment_cmd_count(ctx); // Increment for the write command, regardless of success
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

    // Initialize buffer with non-zero pattern to ensure zeros come from security check
    memset(shared_read_buffer, 0xAA, sizeof(shared_read_buffer));

    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int retval = occp_send_read_command(ctx, ctx->slave_addr, test_addr, shared_read_buffer, len);
    increment_cmd_count(ctx); // Increment for the read command, regardless of success
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
        // Randomly choose between read and write (similar to occp_random_test weighting)
        uint8_t is_read = get_random_int() % 2;

        if (is_read) {
            send_invalid_occp_read(ctx);
        } else {
            send_invalid_occp_write(ctx);
        }
    }
}

static bool test_boundary_cases(test_context_t *ctx) {

    simputs("\n=== Testing Boundary Cases ===\n");

    // Single iteration with random offsets for comprehensive boundary testing
    uint16_t len = get_random_occp_write_size();

    // Fill write data with random pattern
    for (int j = 0; j < len; j++) {
        shared_write_buffer[j] = get_random_int() & 0xFF;
    }

    // Test address just below allowed range with random offset
    uint64_t random_offset_below = get_random_int() % 0x20; // 0-31 offset
    uint64_t addr_below = (OCCP_TEST_BASE_ADDR - 1 - random_offset_below) & 0xfffffffc;
    simputshex32("Boundary test: Address just below range (0x", addr_below);
    simputshex32(" offset: ", random_offset_below);

    // Test write
    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_below, shared_write_buffer, len);
    increment_cmd_count(ctx); // Increment for the write command, regardless of success
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("WRITE command sent\n");
    }
    expected_write_access_denied++;

    // Test read with zero check
    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    int read_result =
        occp_send_read_command(ctx, ctx->slave_addr, addr_below, shared_read_buffer, len);
    increment_cmd_count(ctx); // Increment for the read command, regardless of success
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (read_result == OCCP_SUCCESS) {
        simputs("  READ PASS: Security violation detected\n");
    } else {
        simputs("READ command failed\n");
        ctx->overall_result = false;
    }
    expected_read_access_denied++;

    // above the range is only invalid in secure mode
    if (is_secure_mode()) {
        // Test address at/above upper boundary with random offset
        uint64_t random_offset_above = get_random_int() % 0x20; // 0-31 offset
        uint64_t addr_above = (OCCP_TEST_UPPER_ADDR + random_offset_above) & 0xfffffffc;
        simputshex32("Boundary test: Address at/above upper boundary (0x", addr_above);
        simputshex32(" offset: ", random_offset_above);

        // Test write
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        write_result =
            occp_send_write_command(ctx, ctx->slave_addr, addr_above, shared_write_buffer, len);
        increment_cmd_count(ctx); // Increment for the write command, regardless of success
        ctx->exp_response_code = OCCP_ERROR_NONE;

        if (write_result != OCCP_SUCCESS) {
            simputs("WRITE command failed\n");
            ctx->overall_result = false;
        } else {
            simputs("WRITE command sent\n");
        }
        expected_write_access_denied++;

        // Test read with zero check
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_above, shared_read_buffer, len);
        increment_cmd_count(ctx); // Increment for the read command, regardless of success
        ctx->exp_response_code = OCCP_ERROR_NONE;

        if (read_result == OCCP_SUCCESS) {
            simputs("  READ PASS: Security violation detected\n");
        } else {
            simputs("READ command failed\n");
            ctx->overall_result = false;
        }
        expected_read_access_denied++;
    }

    // re-latch to recover
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // test at SRAM base address (invalid in both secure and unsecure mode)
    uint64_t addr_sram_base = SMC_SRAM_BASE_ADDR;
    simputshex32("Boundary test: Address at SRAM base (0x", addr_sram_base);
    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_sram_base, shared_write_buffer, len);
    increment_cmd_count(ctx); // Increment for the write command
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Security violation detected...\n");
    }
    expected_write_access_denied++;

    // Test read with zero check
    ctx->exp_response_code = OCCP_INVALID_ADDRESS;
    read_result =
        occp_send_read_command(ctx, ctx->slave_addr, addr_sram_base, shared_read_buffer, len);
    increment_cmd_count(ctx); // Increment for the read command, regardless of success
    ctx->exp_response_code = OCCP_ERROR_NONE;

    if (read_result == OCCP_SUCCESS) {
        simputs("  READ PASS: Security violation detected\n");
    } else {
        simputs("READ command failed\n");
        ctx->overall_result = false;
    }
    expected_read_access_denied++;

    // Test valid boundary addresses inside the allowed range
    // Test address at start of valid range with random offset
    uint64_t random_offset_start = (get_random_int() % 0x20) & 0xfffffffc; // 0-31 offset
    uint64_t addr_valid_start = OCCP_TEST_BASE_ADDR + random_offset_start;
    simputshex32("Boundary test: Valid address at start of range (0x", addr_valid_start);
    simputshex32(" offset: ", random_offset_start);

    // Test write to valid start boundary
    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_valid_start, shared_write_buffer, len);
    increment_cmd_count(ctx); // Increment for the write command

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Valid boundary address write succeeded\n");

        // Read back and verify data integrity
        memset(shared_read_buffer, 0x00, sizeof(shared_read_buffer)); // Clear buffer
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_valid_start, shared_read_buffer, len);
        increment_cmd_count(ctx); // Increment for the read command

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

    // Test address just before end of valid range with random offset
    uint64_t random_offset_end = get_random_int() % 0x20; // 0-31 offset
    uint64_t addr_valid_end = (OCCP_TEST_UPPER_ADDR - 8 - len - random_offset_end) &
                              0xfffffffc; // Ensure we don't exceed boundary
    simputshex32("Boundary test: Valid address near end of range (0x", addr_valid_end);
    simputshex32(" offset: ", random_offset_end);

    // Test write to valid end boundary
    write_result =
        occp_send_write_command(ctx, ctx->slave_addr, addr_valid_end, shared_write_buffer, len);
    increment_cmd_count(ctx); // Increment for the write command

    if (write_result != OCCP_SUCCESS) {
        simputs("WRITE command failed\n");
        ctx->overall_result = false;
    } else {
        simputs("  WRITE PASS: Valid boundary address write succeeded\n");

        // Read back and verify data integrity
        memset(shared_read_buffer, 0x00, sizeof(shared_read_buffer)); // Clear buffer
        read_result =
            occp_send_read_command(ctx, ctx->slave_addr, addr_valid_end, shared_read_buffer, len);
        increment_cmd_count(ctx); // Increment for the read command

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

    return true;
}

static void run_security_access_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Secure Mode Access Restriction Test ===\n");

    ctx->overall_result = true;
    ctx->cmd_count = 0;
    ctx->exp_occp_last_error = 0;
    expected_read_access_denied = 0;
    expected_write_access_denied = 0;

    // Test 1: Boundary cases
    test_boundary_cases(ctx);

    // re-latch to recover
    uint32_t status_data = 0;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Test 2: Random interspersed reads and writes to invalid addresses
    simputs("\n=== Testing Random Invalid Operations (Interspersed R/W) ===\n");
    execute_random_invalid_operations(ctx, NUM_RANDOM_OPERATIONS);
    // re-latch to recover
    retval = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: Failed to get version command\n");
        ctx->overall_result = false;
    }
    increment_cmd_count(ctx);

    // Test 3: Valid operations for control (using existing valid address range)
    simputs("\n=== Control Test: Valid Operations ===\n");
    ctx->test_base_addr = OCCP_TEST_BASE_ADDR;                     // Safe offset within valid range
    ctx->test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR; // Safe upper bound

    // Use existing random command execution for valid operations
    execute_random_commands(ctx, NUM_VALID_CONTROL_OPS);

    // Validate that SMC status buffer logged access violations and counts match expectations
    validate_smc_status_buffer_for_secure_access(ctx, expected_read_access_denied,
                                                 expected_write_access_denied);
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        simputs("\nALL SECURITY ACCESS TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
        test_pass(0);
    } else {
        simputs("\nSOME SECURITY ACCESS TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
        test_fail(0);
    }

    occp_send_write_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
                            (uint8_t *)&result_code, sizeof(result_code));
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    // Initialize interface and discover devices
    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    // Set up the rest of the test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;                     // Start of valid range
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR; // End of valid range
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    // Run the security access restriction test suite
    run_security_access_test_suite(&test_ctx);

    // Finalize and report results
    finalize_test_results(&test_ctx);

    return test_ctx.overall_result ? 0 : -1;
}
