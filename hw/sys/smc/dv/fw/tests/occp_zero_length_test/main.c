/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Zero Length Operations Test
 *
 * This test exercises zero length write and read operations and pins the
 * target's documented reaction to them.
 *
 * Specification basis (ROM prod docs, this revision):
 *  - occp-protocol.adoc:310-313 -- error code 0x03 `Invalid_header` is returned
 *    when "A command body length or encoded transfer size is invalid". A zero
 *    encoded WLen/RLen is such an invalid transfer size.
 *  - status-coordination.adoc:186-196 -- 0x120 SMC_OCCP_ERROR_READ_OVERFLOW is
 *    "Invalid or excessive ReadData size"; 0x130 SMC_OCCP_ERROR_WRITE_OVERFLOW
 *    is "Invalid or excessive write-command length".
 *
 * The ROM implements both halves together, so a zero-length command produces a
 * status-buffer record *and* an error response -- these are not alternatives:
 *  - WRITE, bootrom/prod/lib/src/occp.c:1181-1186 -- on `write_size == 0` it
 *    calls smc_status_report(..., SMC_OCCP_ERROR_WRITE_OVERFLOW) and then
 *    smc_occp_handle_error_response(..., Invalid_header), returning
 *    OCCP_ERROR_BUFFER_OVERFLOW.
 *  - READ, occp.c:1324-1330 -- the same shape with
 *    SMC_OCCP_ERROR_READ_OVERFLOW and Invalid_header.
 *  - occp.c:806-813 -- because the handler returned non-none, the OCCP main
 *    loop additionally latches the internal error code (occp.c:810) and emits a
 *    companion SMC_OCCP_ERROR_CMD_FAILED | ret status record.
 *
 * Test Cases:
 * 1. Zero length write operations at various addresses
 * 2. Zero length read operations at various addresses
 * 3. The latched internal OCCP error code after those operations
 * 4. Exact accounting of the resulting SMC status buffer records
 */

#include "occp_test_common.h"
#include "smc_occp_error_codes.h" /* SMC_OCCP_ERROR_{READ,WRITE}_OVERFLOW, _CMD_FAILED */
#include "smc_status.h"           /* SMC_STATUS_FW_ID_SMC_BL0, SMC_STATUS_TYPE_ERROR */

/*
 * Internal OCCP error-code field reported by GET_OCCP_ERROR_CODE (status ID 3).
 * The ROM names this OCCP_ERROR_BUFFER_OVERFLOW = 0x06 in
 * hw/sys/smc/bootrom/prod/lib/include/smc_occp_status.h:61. Only
 * bootrom/prod/include is on the DV firmware include path (fw.mk:41-43), so the
 * value is restated here together with the header that owns it rather than
 * hand-copied without provenance.
 */
#define OCCP_INTERNAL_ERROR_BUFFER_OVERFLOW 0x06u

// Function to read and validate SMC status buffer entries
static void validate_smc_status_buffer(test_context_t *ctx, int exp_write_errors,
                                       int exp_read_errors) {
    uint32_t smc_status = 0;
    int retval;
    int total_write_errors = 0;
    int total_read_errors = 0;

    simputs("=== Validating SMC Status Buffer ===\n");

    // Read all status entries from SMC status buffer
    simputs("Reading SMC status buffer entries:\n");

    /*
     * Bound the drain. Each zero-length command contributes at most two records
     * (the *_OVERFLOW report from the handler and the CMD_FAILED companion from
     * the OCCP main loop); the slack covers boot-sequence records already in the
     * ring when this runs. A target that keeps returning non-zero status must
     * fail here by name rather than as an opaque whole-run timeout.
     */
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

        /*
         * Decode per create_status_msg(), bootrom/prod/lib/src/smc_status.c:19-23:
         *   ((msg_type & 0xFF) << 24) | ((fw_id & 0xFF) << 16) | (msg_value & 0xFFFF)
         * so msg_type is [31:24], fw_id is [23:16] and msg_value is [15:0].
         * occp_boot_sequence_status_test/main.c:119-124 decodes the same way.
         */
        uint32_t msg_type = (smc_status >> 24) & 0xFF;
        uint32_t fw_id = (smc_status >> 16) & 0xFF;
        uint32_t msg_value = smc_status & 0xFFFF;

        if (fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
            simputshex32("FAIL: status record from unexpected fw_id: 0x", smc_status);
            ctx->overall_result = false;
            continue;
        }

        if (msg_type != SMC_STATUS_TYPE_ERROR) {
            /*
             * Boot-sequence informational and warning records share this ring
             * buffer (see occp_boot_sequence_status_test). They are not errors,
             * but log every one so nothing leaves the buffer unaccounted for.
             */
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
            /*
             * Expected companion record: occp.c:811-813 emits
             * SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED, ret) for every
             * handler that returns non-none. Matched with the ROM's own base
             * macro, and range-limited so a wider code cannot alias into it.
             */
            simputshex32("  companion SMC_OCCP_ERROR_CMD_FAILED record: 0x", msg_value);
        } else {
            simputshex32("FAIL: Found unknown error: 0x", msg_value);
            ctx->overall_result = false;
        }
    }

    // Summary and validation
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

/*
 * Read back the internal OCCP error code the ROM latched for the last failing
 * command. GET_OCCP_ERROR_CODE is status ID 3, and occp.c:1033-1037 returns
 * ((occp_status_reg >> 16) & 0xFF) in bits [7:0] of the response word. The OCCP
 * main loop latches the failing handler's return code at occp.c:810, and both
 * zero-length paths return OCCP_ERROR_BUFFER_OVERFLOW.
 *
 * Successful commands do not clear the field (occp.c:801-805 resets only the
 * post code and the interface error count), so it still holds the zero-length
 * result when this runs.
 */
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

    /*
     * A zero encoded write length is an invalid transfer size, so the target
     * must answer with error code 0x03 Invalid_header (occp-protocol.adoc:310-313,
     * implemented at occp.c:1181-1186). Pinning the exact code with
     * exp_response_code makes occp_get_response_header compare it for us
     * (occp_commands.c:331-334) and, just as importantly, makes a timeout, a
     * null driver, a CRC failure or any other error code a FAIL instead of an
     * accidental pass.
     */
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

    /* Same rule on the READ side: occp.c:1324-1330 answers Invalid_header. */
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

    // Test at base address
    test_zero_length_write(ctx, ctx->test_base_addr);
    test_zero_length_read(ctx, ctx->test_base_addr);
    num_write_errors++;
    num_read_errors++;

    // Test at offset addresses
    test_zero_length_write(ctx, ctx->test_upper_addr_bound - 1);
    test_zero_length_read(ctx, ctx->test_upper_addr_bound - 1);
    num_write_errors++;
    num_read_errors++;

    // Test multiple consecutive zero length operations
    simputs("=== Testing Random Zero Length Operations ===\n");
    for (int i = 0; i < 10; i++) {
        if (get_random_int() % 2) { // write or read
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
    /*
     * Sample the latched internal error code before the status drain issues its
     * own traffic, so the value under test is the one the zero-length
     * operations produced.
     */
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

    // Initialize interface and discover devices
    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    // Set up test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    simputs("=== First execute random commands (5 commands) ===\n");
    execute_random_commands(&test_ctx, 5);

    // Run the comprehensive zero length tests
    run_zero_length_tests(&test_ctx);

    simputs("=== Second execute random commands (5 commands) ===\n");
    execute_random_commands(&test_ctx, 5);

    // Finalize and report results
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
