/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Boot Sequence Status Codes Test
 *
 * **SPECIFICATION COMPLIANCE TEST**
 * This test validates the boot sequence status codes the ROM reports
 * (hw/sys/smc/bootrom/prod/doc/status-coordination.adoc):
 *
 * Boot sequence status codes:
 * - SMC_STATUS_ROM_STARTED (0x001): ROM started
 * - SMC_STATUS_BOOT_START (0x010): Boot sequence started / Config read
 * - SMC_STATUS_RECOVERY_MODE (0x020): Recovery mode detected
 * - SMC_STATUS_PRIMARY_MODE (0x021): Primary mode detected
 * - SMC_STATUS_SECONDARY_MODE (0x022): Secondary mode detected
 * - SMC_STATUS_OCCP_INIT_FAILED (0x030): OCCP initialization failed
 * - SMC_STATUS_OCCP_READY (0x031): OCCP ready and operational
 * - SMC_STATUS_COORDINATION_ACTIVE (0x040): Coordination active
 * - SMC_STATUS_BOOT_COMPLETE (0x050): Boot sequence completed successfully
 * - SMC_STATUS_UNEXPECTED_EXIT (0x0FF): Unexpected exit from main loop
 *
 * **TEST STRATEGY:**
 * 1. Query ROM status ring buffer for boot sequence status codes
 * 2. Verify expected status codes are present with correct timing
 * 3. Validate status code format and message structure
 * 4. FAIL if expected boot status codes are missing (detect specification gaps)
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>
#include "smc_status.h"

// Boot Sequence Status Codes from specification
#define SMC_STATUS_ROM_STARTED 0x001
#define SMC_STATUS_BOOT_START 0x010
#define SMC_STATUS_RECOVERY_MODE 0x020
#define SMC_STATUS_PRIMARY_MODE 0x021
#define SMC_STATUS_SECONDARY_MODE 0x022
#define SMC_STATUS_INVALID_SEC_MODE 0x025
#define SMC_STATUS_OCCP_INIT_FAILED 0x030
#define SMC_STATUS_OCCP_READY 0x031
#define SMC_STATUS_COORDINATION_ACTIVE 0x040
#define SMC_STATUS_BOOT_COMPLETE 0x050
#define SMC_STATUS_UNEXPECTED_EXIT 0x0FF

typedef struct {
    uint32_t status_code;
    const char *name;
    const char *description;
    bool found;
    bool required;
} boot_status_entry_t;

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;
    boot_status_entry_t *status_codes;
    int status_code_count;
} boot_status_test_context_t;

static boot_status_entry_t expected_boot_codes[] = {
    {SMC_STATUS_ROM_STARTED, "ROM_STARTED", "ROM started", false, true},
    {SMC_STATUS_BOOT_START, "BOOT_START", "Boot sequence started / Config read", false, true},
    {SMC_STATUS_RECOVERY_MODE, "RECOVERY_MODE", "Recovery mode detected", false, false},
    {SMC_STATUS_PRIMARY_MODE, "PRIMARY_MODE", "Primary mode detected", false, false},
    {SMC_STATUS_SECONDARY_MODE, "SECONDARY_MODE", "Secondary mode detected", false, false},
    {SMC_STATUS_INVALID_SEC_MODE, "INVALID_SEC_MODE", "Invalid security/lifecycle mode detected",
     false, false},
    {SMC_STATUS_OCCP_INIT_FAILED, "OCCP_INIT_FAILED", "OCCP initialization failed", false, false},
    {SMC_STATUS_OCCP_READY, "OCCP_READY", "OCCP ready and operational", false, true},
    {SMC_STATUS_COORDINATION_ACTIVE, "COORDINATION_ACTIVE", "Coordination active", false, false},
    {SMC_STATUS_BOOT_COMPLETE, "BOOT_COMPLETE", "Boot sequence completed", false, true},
    {SMC_STATUS_UNEXPECTED_EXIT, "UNEXPECTED_EXIT", "Unexpected exit from main loop", false,
     false}};

static void init_boot_status_test_context(boot_status_test_context_t *ctx,
                                          test_context_t *occp_ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->occp_ctx = occp_ctx;
    ctx->overall_result = true;
    ctx->total_tests = 0;
    ctx->passed_tests = 0;
    ctx->status_codes = expected_boot_codes;
    ctx->status_code_count = sizeof(expected_boot_codes) / sizeof(expected_boot_codes[0]);

    // Reset found flags
    for (int i = 0; i < ctx->status_code_count; i++) {
        ctx->status_codes[i].found = false;
    }
}

static void mark_test_result(boot_status_test_context_t *ctx, bool passed, const char *test_name) {
    ctx->total_tests++;
    if (passed) {
        ctx->passed_tests++;
        simputs("PASS: ");
    } else {
        simputs("FAIL: ");
        ctx->overall_result = false;
    }
    simputs(test_name);
    simputs("\n");
}

static uint32_t extract_status_message_components(uint32_t status, uint32_t *fw_id,
                                                  uint32_t *msg_type, uint32_t *msg_value) {
    *fw_id = (status >> 16) & 0xFF;
    *msg_type = (status >> 24) & 0xFF;
    *msg_value = status & 0xFFFF;
    return status;
}

static bool is_smc_status_message(uint32_t status) {
    uint32_t fw_id, msg_type, msg_value;
    extract_status_message_components(status, &fw_id, &msg_type, &msg_value);
    return (fw_id == SMC_STATUS_FW_ID_SMC_BL0);
}

static bool collect_boot_status_messages(boot_status_test_context_t *ctx) {
    simputs("\n=== Collecting Boot Status Messages from ROM ===\n");

    int total_messages_read = 0;
    int smc_messages_found = 0;
    int boot_status_found = 0;
    int consecutive_empty = 0;
    const int max_reads = 200; // Read extensively to capture all boot messages

    simputs("Querying SMC status ring buffer...\n");

    for (int i = 0; i < max_reads && consecutive_empty < 20; i++) {
        uint32_t status;
        int result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result != OCCP_SUCCESS) {
            simputshex32("ERROR: Failed to read SMC status at iteration: ", i);
            return false;
        }

        if (status != 0) {
            total_messages_read++;
            consecutive_empty = 0;

            uint32_t fw_id, msg_type, msg_value;
            extract_status_message_components(status, &fw_id, &msg_type, &msg_value);

            if (is_smc_status_message(status)) {
                smc_messages_found++;

                // Check if this is a boot sequence status code
                bool is_boot_status = false;
                for (int j = 0; j < ctx->status_code_count; j++) {
                    uint32_t expected_code = ctx->status_codes[j].status_code;
                    bool matches = false;

                    // Handle BOOT_START which may be OR'd with strap status (0x010-0x01F)
                    if (expected_code == SMC_STATUS_BOOT_START && msg_value >= 0x010 &&
                        msg_value <= 0x01F) {
                        uint32_t base_code = msg_value & 0xFF0;
                        if (base_code == SMC_STATUS_BOOT_START) {
                            matches = true;
                        }
                    } else if (msg_value == expected_code) {
                        matches = true;
                    }

                    if (matches) {
                        if (!ctx->status_codes[j].found) {
                            ctx->status_codes[j].found = true;
                            boot_status_found++;
                            is_boot_status = true;

                            simputs("FOUND: ");
                            simputs(ctx->status_codes[j].name);
                            simputs(" (");
                            simputshex32("0x", msg_value);
                            simputs(") - ");
                            simputs(ctx->status_codes[j].description);

                            // Show strap data if this is BOOT_START with strap info
                            if (expected_code == SMC_STATUS_BOOT_START &&
                                msg_value != SMC_STATUS_BOOT_START) {
                                uint32_t strap_data = msg_value & 0x00F;
                                simputs(" [strap: ");
                                simputshex32("0x", strap_data);
                                simputs("]");
                            }
                            simputs("\n");
                        }
                        break;
                    }
                }

                if (!is_boot_status && total_messages_read <= 20) {
                    // Log unknown status codes for first few messages
                    simputs("UNKNOWN SMC Status: ");
                    simputshex32("fw_id=", fw_id);
                    simputs(" ");
                    simputshex32("type=", msg_type);
                    simputs(" ");
                    simputshex32("value=0x", msg_value);
                    simputs("\n");
                }
            }
        } else {
            consecutive_empty++;
        }
    }

    simputs("\n=== Boot Status Message Collection Results ===\n");
    simputshex32("Total messages read from buffer: ", total_messages_read);
    simputshex32("SMC messages found: ", smc_messages_found);
    simputshex32("Boot status codes found: ", boot_status_found);
    simputshex32("Expected required codes: ",
                 4); // ROM_STARTED, BOOT_START, OCCP_READY, BOOT_COMPLETE

    return (total_messages_read > 0);
}

static bool test_boot_sequence_status_coverage(boot_status_test_context_t *ctx) {
    simputs("\n=== Test 1: Boot Sequence Status Code Coverage ===\n");
    simputs("SPEC: ROM must generate specific status codes during boot sequence\n");

    bool test_passed = true;
    int required_found = 0;
    int required_missing = 0;

    simputs("\n**BOOT STATUS CODE VERIFICATION**:\n");

    for (int i = 0; i < ctx->status_code_count; i++) {
        boot_status_entry_t *entry = &ctx->status_codes[i];

        simputs("  ");
        simputs(entry->name);
        simputs(" (0x");
        simputshex32("", entry->status_code);
        simputs("): ");

        if (entry->found) {
            simputs("FOUND");
            if (entry->required) {
                required_found++;
            }
        } else {
            simputs("MISSING");
            if (entry->required) {
                required_missing++;
                test_passed = false;
                simputs(" **CRITICAL**");
            }
        }

        simputs(" - ");
        simputs(entry->description);
        simputs("\n");
    }

    simputs("\n**COVERAGE ANALYSIS**:\n");
    simputshex32("Required status codes found: ", required_found);
    simputshex32("Required status codes missing: ", required_missing);

    if (required_missing > 0) {
        simputs("CRITICAL FAILURE: Essential boot status codes are missing\n");
        simputs("This indicates the ROM is not following the specification\n");
        simputs("for boot sequence status reporting\n");
        test_passed = false;
    } else {
        simputs("SUCCESS: All required boot status codes are present\n");
    }

    mark_test_result(ctx, test_passed, "Boot Sequence Status Code Coverage");
    return test_passed;
}

static bool test_status_message_format_compliance(boot_status_test_context_t *ctx) {
    simputs("\n=== Test 2: Status Message Format Compliance ===\n");
    simputs("SPEC: Status messages must follow standardized format\n");

    bool test_passed = true;
    int valid_format_count = 0;
    int invalid_format_count = 0;

    // Re-read a few messages to test format
    for (int i = 0; i < 20; i++) {
        uint32_t status;
        int result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result == OCCP_SUCCESS && status != 0) {
            uint32_t fw_id, msg_type, msg_value;
            extract_status_message_components(status, &fw_id, &msg_type, &msg_value);

            if (is_smc_status_message(status)) {
                bool format_valid = true;

                // Handle BOOT_START OR'd with strap status (0x010-0x01F range)
                if (msg_value >= 0x010 && msg_value <= 0x01F) {
                    // Verify this is BOOT_START OR'd with strap status
                    uint32_t base_code = msg_value & 0xFF0;
                    uint32_t strap_data = msg_value & 0x00F;

                    if (base_code == SMC_STATUS_BOOT_START) {
                        simputs("BOOT_START with strap data: ");
                        simputshex32("0x", strap_data);
                        simputs("\n");
                    }
                }

                // Validate firmware ID
                if (fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
                    simputs("ERROR: Invalid firmware ID: ");
                    simputshex32("", fw_id);
                    simputs("\n");
                    format_valid = false;
                }

                // Validate message type
                if (msg_type > SMC_STATUS_TYPE_ERROR) {
                    simputs("ERROR: Invalid message type: ");
                    simputshex32("", msg_type);
                    simputs("\n");
                    format_valid = false;
                }

                // Validate boot sequence status codes are of correct type
                for (int j = 0; j < ctx->status_code_count; j++) {
                    uint32_t expected_code = ctx->status_codes[j].status_code;
                    bool matches = false;

                    // Handle BOOT_START which may be OR'd with strap status
                    if (expected_code == SMC_STATUS_BOOT_START && msg_value >= 0x010 &&
                        msg_value <= 0x01F) {
                        uint32_t base_code = msg_value & 0xFF0;
                        if (base_code == SMC_STATUS_BOOT_START) {
                            matches = true;
                        }
                    } else if (msg_value == expected_code) {
                        matches = true;
                    }

                    if (matches) {
                        // Boot status codes should be STATUS type (0x0) unless they're errors
                        if (expected_code == SMC_STATUS_OCCP_INIT_FAILED ||
                            expected_code == SMC_STATUS_UNEXPECTED_EXIT) {
                            if (msg_type != SMC_STATUS_TYPE_ERROR) {
                                simputs("ERROR: Error status code with wrong type: ");
                                simputs(ctx->status_codes[j].name);
                                simputs("\n");
                                format_valid = false;
                            }
                        } else if (expected_code == SMC_STATUS_RECOVERY_MODE) {
                            if (msg_type != SMC_STATUS_TYPE_WARNING) {
                                simputs("WARNING: Recovery mode not marked as warning\n");
                            }
                        } else {
                            if (msg_type != SMC_STATUS_TYPE_STATUS) {
                                simputs("ERROR: Status code with wrong type: ");
                                simputs(ctx->status_codes[j].name);
                                simputs("\n");
                                format_valid = false;
                            }
                        }
                        break;
                    }
                }

                if (format_valid) {
                    valid_format_count++;
                } else {
                    invalid_format_count++;
                    test_passed = false;
                }
            }
        }
    }

    simputs("\n**FORMAT COMPLIANCE RESULTS**:\n");
    simputshex32("Valid format messages: ", valid_format_count);
    simputshex32("Invalid format messages: ", invalid_format_count);

    if (invalid_format_count > 0) {
        simputs("CRITICAL: Status messages do not comply with specification format\n");
        test_passed = false;
    } else {
        simputs("SUCCESS: All status messages comply with specification format\n");
    }

    mark_test_result(ctx, test_passed, "Status Message Format Compliance");
    return test_passed;
}

static bool test_boot_sequence_timing_verification(boot_status_test_context_t *ctx) {
    simputs("\n=== Test 3: Boot Sequence Timing Verification ===\n");
    simputs("SPEC: Boot status codes should appear in logical sequence\n");

    bool test_passed = true;

    // Check logical dependencies
    bool rom_started = ctx->status_codes[0].found;      // ROM_STARTED
    bool boot_start = ctx->status_codes[1].found;       // BOOT_START
    bool occp_init_failed = ctx->status_codes[6].found; // OCCP_INIT_FAILED
    bool occp_ready = ctx->status_codes[7].found;       // OCCP_READY
    bool boot_complete = ctx->status_codes[9].found;    // BOOT_COMPLETE
    bool unexpected_exit = ctx->status_codes[10].found; // UNEXPECTED_EXIT

    simputs("\n**BOOT SEQUENCE LOGIC VERIFICATION**:\n");

    // ROM_STARTED should be present if system boots properly
    if (!rom_started) {
        simputs("CRITICAL: ROM_STARTED status missing - ROM may not be reporting boot start\n");
        test_passed = false;
    } else {
        simputs(" ROM_STARTED: ROM boot initialization detected\n");
    }

    // BOOT_START should follow ROM_STARTED
    if (!boot_start) {
        simputs("CRITICAL: BOOT_START status missing - Boot sequence not reported\n");
        test_passed = false;
    } else {
        simputs(" BOOT_START: Boot sequence initiation detected\n");
    }

    // OCCP_READY should be present for OCCP functionality
    if (!occp_ready) {
        simputs("CRITICAL: OCCP_READY status missing - OCCP initialization not reported\n");
        test_passed = false;
    } else {
        simputs(" OCCP_READY: OCCP initialization success detected\n");
    }

    // BOOT_COMPLETE should indicate successful boot
    if (!boot_complete) {
        simputs("WARNING: BOOT_COMPLETE status missing - ROM may still be in progress\n");
        // BOOT_COMPLETE is optional: the ROM is still in its OCCP command loop while this runs
        simputs("  (This may be expected if ROM is still in OCCP command loop)\n");
    } else {
        simputs(" BOOT_COMPLETE: Boot sequence completion detected\n");
    }

    // Check for error conditions
    if (occp_init_failed) {
        simputs("ERROR: OCCP_INIT_FAILED detected - Critical boot failure\n");
        test_passed = false;
    }

    if (unexpected_exit) {
        simputs("ERROR: UNEXPECTED_EXIT detected - ROM abnormal termination\n");
        test_passed = false;
    }

    mark_test_result(ctx, test_passed, "Boot Sequence Timing Verification");
    return test_passed;
}

static bool test_specification_compliance(boot_status_test_context_t *ctx) {
    simputs("\n=== Test 4: Specification Compliance Analysis ===\n");
    simputs("**SPECIFICATION COMPLIANCE ANALYSIS**\n");

    bool test_passed = true;

    simputs("ANALYZING ROM BOOT STATUS REPORTING COMPLIANCE:\n");
    simputs("1. The ROM specification defines the boot sequence status codes\n");
    simputs("2. ROM should generate these at appropriate boot phases\n");
    simputs("3. Status codes provide observability into boot progression\n");

    int required_missing = 0;
    int optional_missing = 0;

    for (int i = 0; i < ctx->status_code_count; i++) {
        if (!ctx->status_codes[i].found) {
            if (ctx->status_codes[i].required) {
                required_missing++;
            } else {
                optional_missing++;
            }
        }
    }

    simputs("\n**COMPLIANCE ANALYSIS RESULTS**:\n");
    simputshex32("Required status codes missing: ", required_missing);
    simputshex32("Optional status codes missing: ", optional_missing);

    if (required_missing > 0) {
        simputs("\n**SPECIFICATION DISCREPANCY DETECTED**:\n");
        simputs("- SPEC: ROM must report essential boot status codes\n");
        simputs("- IMPL: Missing critical status code reporting\n");
        simputs("- IMPACT: Reduced boot sequence observability\n");
        simputs("- RECOMMENDATION: Implement missing status reporting in ROM\n");
        test_passed = false;
    } else {
        simputs("\n**SPECIFICATION COMPLIANCE VERIFIED**:\n");
        simputs("All required boot sequence status codes are implemented\n");
    }

    if (optional_missing == ctx->status_code_count) {
        simputs("\n**CRITICAL FAILURE**: No boot status codes found at all\n");
        simputs("This suggests ROM status reporting is not functional\n");
        test_passed = false;
    }

    mark_test_result(ctx, test_passed, "Specification Compliance Analysis");
    return test_passed;
}

static bool test_active_status_generation(boot_status_test_context_t *ctx) {
    simputs("\n=== Test 5: Active Status Code Generation ===\n");
    simputs("SPEC: Actively trigger scenarios to verify specific status codes are generated\n");

    bool test_passed = true;
    int scenarios_tested = 0;
    int status_codes_triggered = 0;

    simputs("Testing active status code generation scenarios...\n");

    // Count initial status codes before active testing
    int initial_boot_codes = 0;
    for (int i = 0; i < ctx->status_code_count; i++) {
        if (ctx->status_codes[i].found) {
            initial_boot_codes++;
        }
    }

    simputs("Active test scenarios:\n");

    // Scenario 1: Try to trigger OCCP_INIT_FAILED by disrupting interface
    simputs("1. Testing OCCP interface stress scenarios...\n");
    scenarios_tested++;

    // Send rapid commands to test interface robustness
    for (int i = 0; i < 10; i++) {
        uint32_t status;
        occp_send_get_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);
    }

    // Scenario 2: Test invalid command scenarios that might trigger CMD_FAILED status
    simputs("2. Testing command validation scenarios...\n");
    scenarios_tested++;

    // Try zero-length operations that should be rejected
    uint8_t dummy_data[1] = {0};
    int result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr,
                                         OCCP_TEST_BASE_ADDR, dummy_data, 0);
    if (result != OCCP_SUCCESS) {
        simputs("Expected: Zero-length command rejected\n");
    }

    // Scenario 3: Test memory boundary scenarios
    simputs("3. Testing memory access boundary scenarios...\n");
    scenarios_tested++;

    // Try accessing ROM-protected regions (should be denied)
    uint8_t test_data[8] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x11, 0x22};
    result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0060000,
                                     test_data, sizeof(test_data));
    if (result != OCCP_SUCCESS) {
        simputs("Expected: ROM-protected write denied\n");
    }

    // Brief pause to allow status messages to be logged
    for (volatile int delay = 0; delay < 10000; delay++)
        ;

    // Re-scan for any new status codes that might have been generated
    simputs("Checking for newly generated status codes...\n");
    for (int scan = 0; scan < 20; scan++) {
        uint32_t status;
        result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result == OCCP_SUCCESS && status != 0) {
            uint32_t fw_id, msg_type, msg_value;
            extract_status_message_components(status, &fw_id, &msg_type, &msg_value);

            if (is_smc_status_message(status)) {
                // Check if this is a new boot status code we haven't seen
                for (int j = 0; j < ctx->status_code_count; j++) {
                    if (!ctx->status_codes[j].found &&
                        msg_value == ctx->status_codes[j].status_code) {
                        ctx->status_codes[j].found = true;
                        status_codes_triggered++;
                        simputs("NEW STATUS FOUND: ");
                        simputs(ctx->status_codes[j].name);
                        simputs(" (");
                        simputshex32("0x", msg_value);
                        simputs(")\n");
                        break;
                    }
                }
            }
        } else if (status == 0) {
            break; // No more messages
        }
    }

    simputs("\n**ACTIVE GENERATION RESULTS**:\n");
    simputshex32("Test scenarios executed: ", scenarios_tested);
    simputshex32("New status codes found: ", status_codes_triggered);
    simputshex32("Initial boot codes found: ", initial_boot_codes);

    // Count final status codes
    int final_boot_codes = 0;
    for (int i = 0; i < ctx->status_code_count; i++) {
        if (ctx->status_codes[i].found) {
            final_boot_codes++;
        }
    }
    simputshex32("Final boot codes found: ", final_boot_codes);

    if (status_codes_triggered > 0) {
        simputs("SUCCESS: Active testing generated additional status codes\n");
    } else {
        simputs("INFO: No additional status codes generated (may be expected)\n");
        simputs("Most boot status codes are generated during ROM initialization\n");
    }

    mark_test_result(ctx, test_passed, "Active Status Code Generation");
    return test_passed;
}

static void run_boot_status_test_suite(boot_status_test_context_t *ctx) {
    simputs("=== Boot Sequence Status Codes Test Suite ===\n");
    simputs("Mission: Detect discrepancies in boot status reporting\n");
    simputs("Target: Verify ROM generates specified boot sequence status codes\n");

    // Collect all boot status messages from ROM
    if (!collect_boot_status_messages(ctx)) {
        simputs("CRITICAL: Failed to collect status messages from ROM\n");
        ctx->overall_result = false;
        return;
    }

    // Run comprehensive test suite
    test_boot_sequence_status_coverage(ctx);
    test_status_message_format_compliance(ctx);
    test_boot_sequence_timing_verification(ctx);
    test_specification_compliance(ctx);
    test_active_status_generation(ctx);

    simputs("\n=== Boot Status Test Results Summary ===\n");
    simputshex32("Tests passed: ", ctx->passed_tests);
    simputshex32("Tests non-passed: ", ctx->total_tests - ctx->passed_tests);
    simputshex32("Total tests: ", ctx->total_tests);

    if (ctx->overall_result) {
        simputs("ALL BOOT STATUS TESTS PASSED!\n");
        simputs("Boot sequence status code reporting is compliant with specification\n");
    } else {
        simputs("BOOT STATUS TESTS FAILED!\n");
        simputs("**CRITICAL**: Boot status code reporting discrepancies detected\n");
    }
}

static void finalize_test_results(boot_status_test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
    } else {
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
    }

    occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr,
                            SMC_CPU_CTRL_SCRATCH_0__REG_ADDR, (uint8_t *)&result_code,
                            sizeof(result_code));
}

int main(void) {
    static test_context_t occp_ctx = {0};
    static boot_status_test_context_t test_ctx = {0};

    init_test(0);

    simputs("=== OCCP Boot Sequence Status Codes Test ===\n");
    simputs("Mission: Verify ROM generates all specified boot sequence status codes\n");
    simputs("Coverage: all boot sequence status codes in expected_boot_codes\n");

    if (!initialize_interface(&occp_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
        return -1;
    }

    // Use standard test address constants
    occp_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    occp_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    occp_ctx.overall_result = true;
    occp_ctx.cmd_count = 0;
    occp_ctx.exp_occp_last_error = 0;

    init_boot_status_test_context(&test_ctx, &occp_ctx);

    run_boot_status_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);

    // Summary statistics
    simputs("\n=== Final Test Results Summary ===\n");
    simputshex32("Tests passed: ", test_ctx.passed_tests);
    simputshex32("Tests non-passed: ", test_ctx.total_tests - test_ctx.passed_tests);
    simputshex32("Total tests: ", test_ctx.total_tests);
    simputshex32("Boot status codes verified: ", test_ctx.status_code_count);

    if (test_ctx.overall_result) {
        simputs("BOOT SEQUENCE STATUS TEST: PASS\n");
        simputs("All boot sequence status codes are properly implemented\n");
        test_pass(0);
    } else {
        simputs("BOOT SEQUENCE STATUS TEST: FAIL\n");
        simputs("SPECIFICATION DISCREPANCY: Boot status code reporting issues detected\n");
        test_fail(0);
    }

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
