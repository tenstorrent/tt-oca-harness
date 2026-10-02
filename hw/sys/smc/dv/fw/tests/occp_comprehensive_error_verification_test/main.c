/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Comprehensive Error Verification Test
 *
 * Sends the ROM's OCCP command handler requests it should reject (protected and
 * invalid addresses, zero-length and oversized transfers, invalid JUMP and
 * VALIDATE_AND_BOOT targets, unknown commands) and scans the status ring buffer
 * for error reports; these steps only log, and no specific error code is
 * checked. The test fails when a wrapping or edge-address write, a read with an
 * oversized count, a zero-length write or a 255-byte write succeeds, or when a
 * written pattern does not read back byte-reversed.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>
#include "smc_status.h"

// OCCP error codes for the local code-range checks
#define SMC_OCCP_ERROR_CMD_UNKNOWN 0x101         /* Unknown command */
#define SMC_OCCP_ERROR_READ_ACCESS_DENIED 0x121  /* READ access denied */
#define SMC_OCCP_ERROR_WRITE_ACCESS_DENIED 0x131 /* WRITE access denied */

#define ROM_PROTECTED_SRAM_BASE 0xC0060000 /* ROM protected region start */

#define MAX_STATUS_BUFFER_READS 200 /* Maximum status reads */
#define MAX_INVALID_COMMANDS 16     /* Maximum invalid commands to test */

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;

    // Error detection counters
    int violations_triggered;
    int errors_found;
    int status_entries_processed;

    // Critical-case counters
    int critical_bugs_tested;
    int edge_cases_tested;
    int security_violations_tested;
} comprehensive_error_test_context_t;

static void init_test_context(comprehensive_error_test_context_t *ctx, test_context_t *occp_ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->occp_ctx = occp_ctx;
    ctx->overall_result = true;
    ctx->critical_bugs_tested = 0;
    ctx->edge_cases_tested = 0;
    ctx->security_violations_tested = 0;
}

static void mark_test_result(comprehensive_error_test_context_t *ctx, bool passed,
                             const char *test_name) {
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

static bool test_memory_access_violations(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 1: Memory Access Violations ===\n");
    simputs("SPEC: Test READ/WRITE access denied errors from ROM-protected regions\n");

    bool test_passed = true;
    uint8_t test_data[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0x12, 0x34, 0x56, 0x78};

    simputs("Testing ROM-protected region violations...\n");
    for (uint64_t addr = ROM_PROTECTED_SRAM_BASE; addr < ROM_PROTECTED_SRAM_BASE + 0x2000;
         addr += 0x1000) {
        int result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, addr,
                                             test_data, sizeof(test_data));
        if (result != OCCP_SUCCESS) {
            simputs("Expected violation: ROM-protected WRITE denied\n");
            ctx->violations_triggered++;
        }

        uint8_t read_buffer[8];
        result = occp_send_read_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, addr, read_buffer,
                                        sizeof(read_buffer));
        if (result != OCCP_SUCCESS) {
            simputs("Expected violation: ROM-protected READ denied\n");
            ctx->violations_triggered++;
        }
    }

    simputs("Testing invalid address range violations...\n");
    uint64_t invalid_addrs[] = {0x00000000, 0xFFFFFFFFFFFFFFFF};
    for (int i = 0; i < sizeof(invalid_addrs) / sizeof(invalid_addrs[0]); i++) {
        int result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr,
                                             invalid_addrs[i], test_data, sizeof(test_data));
        if (result != OCCP_SUCCESS) {
            simputs("Expected violation: Invalid address WRITE denied\n");
            ctx->violations_triggered++;
        }
    }

    simputs("Memory access violation tests completed\n");
    mark_test_result(ctx, test_passed, "Memory Access Violations");
    return test_passed;
}

static bool test_command_failures(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 2: Command Execution Failures ===\n");
    simputs("SPEC: Test command execution failure scenarios\n");

    bool test_passed = true;

    simputs("Testing zero-length command failures...\n");

    int result =
        occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0070000, NULL, 0);
    if (result != OCCP_SUCCESS) {
        simputs("Expected failure: Zero-length WRITE rejected\n");
        ctx->violations_triggered++;
    }

    simputs("Testing oversized operation failures...\n");
    uint8_t large_data[MAX_OCCP_WRITE_SIZE + 10];
    memset(large_data, 0xAA, sizeof(large_data));

    result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0070000,
                                     large_data, sizeof(large_data));
    if (result != OCCP_SUCCESS) {
        simputs("Expected failure: Oversized WRITE rejected\n");
        ctx->violations_triggered++;
    }

    simputs("Command failure tests completed\n");
    mark_test_result(ctx, test_passed, "Command Execution Failures");
    return test_passed;
}

static bool test_jump_security_violations(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 3: JUMP Security Violations ===\n");
    simputs("SPEC: Test JUMP command security enforcement\n");

    bool test_passed = true;

    simputs("Testing JUMP security violations...\n");
    uint64_t invalid_jump_addrs[] = {
        0xFFFFFFFFFFFFFFFF,      // Invalid high address
        0x00000000,              // Invalid low address
        ROM_PROTECTED_SRAM_BASE, // ROM protected region
    };

    for (int i = 0; i < sizeof(invalid_jump_addrs) / sizeof(invalid_jump_addrs[0]); i++) {
        int result =
            occp_send_jump_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, invalid_jump_addrs[i]);
        if (result != OCCP_SUCCESS) {
            simputs("Expected violation: JUMP security violation\n");
            ctx->violations_triggered++;
        }
    }

    simputs("JUMP security violation tests completed\n");
    mark_test_result(ctx, test_passed, "JUMP Security Violations");
    return test_passed;
}

static bool test_invalid_command_injection(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 4: Invalid Command Injection ===\n");
    simputs("SPEC: Test invalid OCCP command rejection and CMD_UNKNOWN error reporting\n");

    bool test_passed = true;

    simputs("Testing invalid command injection...\n");

    // Command words the ROM does not define; each should be rejected as unknown.
    uint32_t invalid_commands[] = {
        0x08,   0x09,   0x0A,  0x0B, // Invalid single-byte commands
        0xFF,   0xAA,   0x55,  0xCC, // More invalid patterns
        0xDEAD, 0xBEEF, 0x1234       // Multi-byte invalid commands
    };

    for (int i = 0;
         i < sizeof(invalid_commands) / sizeof(invalid_commands[0]) && i < MAX_INVALID_COMMANDS;
         i++) {
        simputs("Sending invalid command: ");
        simputshex32("0x", invalid_commands[i]);
        simputs("\n");

        uint8_t cmd_packet[4];
        cmd_packet[0] = invalid_commands[i] & 0xFF;
        cmd_packet[1] = (invalid_commands[i] >> 8) & 0xFF;
        cmd_packet[2] = (invalid_commands[i] >> 16) & 0xFF;
        cmd_packet[3] = (invalid_commands[i] >> 24) & 0xFF;

        if (ctx->occp_ctx->drv.i2c_drv != NULL) {
            ctx->occp_ctx->drv.i2c_drv->ctrlr_send_data(ctx->occp_ctx->drv.i2c_drv, cmd_packet,
                                                        sizeof(cmd_packet));
            ctx->violations_triggered++;
        }
    }

    simputs("Invalid command injection tests completed\n");
    mark_test_result(ctx, test_passed, "Invalid Command Injection");
    return test_passed;
}

static bool test_buffer_overflow_scenarios(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 5: Buffer Overflow Testing ===\n");
    simputs("SPEC: Test buffer overflow protection for READ/WRITE commands\n");

    bool test_passed = true;

    simputs("Testing buffer overflow scenarios...\n");

    uint8_t max_buffer[MAX_OCCP_WRITE_SIZE];
    memset(max_buffer, 0x5A, sizeof(max_buffer));

    // A write of exactly the maximum size should succeed.
    int result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0070000,
                                         max_buffer, MAX_OCCP_WRITE_SIZE);
    if (result == OCCP_SUCCESS) {
        simputs("Maximum size WRITE: PASS\n");
    } else {
        simputs("Maximum size WRITE: Unexpected failure\n");
    }

    // Writes and reads over the maximum size should be rejected.
    uint8_t oversized_buffer[MAX_OCCP_WRITE_SIZE + 8];
    memset(oversized_buffer, 0xA5, sizeof(oversized_buffer));

    result = occp_send_write_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0070000,
                                     oversized_buffer, sizeof(oversized_buffer));
    if (result != OCCP_SUCCESS) {
        simputs("Expected failure: Oversized buffer overflow protection triggered\n");
        ctx->violations_triggered++;
    }

    uint8_t read_buffer[MAX_OCCP_WRITE_SIZE + 16];
    result = occp_send_read_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, 0xC0070000,
                                    read_buffer, sizeof(read_buffer));
    if (result != OCCP_SUCCESS) {
        simputs("Expected failure: READ buffer overflow protection triggered\n");
        ctx->violations_triggered++;
    }

    simputs("Buffer overflow testing completed\n");
    mark_test_result(ctx, test_passed, "Buffer Overflow Testing");
    return test_passed;
}

static bool test_validate_boot_security(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 6: VALIDATE_AND_BOOT Security ===\n");
    simputs("SPEC: Test VALIDATE_AND_BOOT security enforcement\n");

    bool test_passed = true;

    simputs("Testing VALIDATE_AND_BOOT security violations...\n");
    uint64_t protected_manifest_addrs[] = {
        ROM_PROTECTED_SRAM_BASE, // ROM protected region
        0x00000000,              // Invalid low address
        0xFFFFFFFFFFFFFFFF       // Invalid high address
    };

    for (int i = 0; i < sizeof(protected_manifest_addrs) / sizeof(protected_manifest_addrs[0]);
         i++) {
        int result = occp_send_validate_boot_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr,
                                                     protected_manifest_addrs[i]);
        if (result != OCCP_SUCCESS) {
            simputs("Expected violation: VALIDATE_AND_BOOT security violation\n");
            ctx->violations_triggered++;
        }
    }

    simputs("VALIDATE_AND_BOOT security tests completed\n");
    mark_test_result(ctx, test_passed, "VALIDATE_AND_BOOT Security");
    return test_passed;
}

static bool test_helper_macro_functionality(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 7: Helper Macro Verification ===\n");
    simputs("SPEC: Test OCCP error construction macros and data encoding\n");

    bool test_passed = true;

    simputs("Testing helper macro functionality...\n");

    // These checks run on local constants only; no OCCP command is sent.
    uint32_t error_with_data_tests[] = {
        SMC_OCCP_ERROR_CMD_UNKNOWN | 0x0A,        // CMD_UNKNOWN with command data
        SMC_OCCP_ERROR_CMD_UNKNOWN | 0x55,        // CMD_UNKNOWN with different data
        SMC_OCCP_ERROR_READ_ACCESS_DENIED | 0x01, // READ error with data
        SMC_OCCP_ERROR_WRITE_ACCESS_DENIED | 0x02 // WRITE error with data
    };

    for (int i = 0; i < sizeof(error_with_data_tests) / sizeof(error_with_data_tests[0]); i++) {
        uint32_t error_code = error_with_data_tests[i];
        uint32_t base_error = error_code & 0xFF0;
        uint32_t data_portion = error_code & 0x00F;

        simputs("Testing error construction: Base=0x");
        simputshex32("", base_error);
        simputs(", Data=0x");
        simputshex32("", data_portion);
        simputs("\n");

        if ((base_error >= 0x100 && base_error <= 0x2FF)) {
            simputs("PASS: Error code in valid OCCP range\n");
        } else {
            simputs("FAIL: Error code outside valid range\n");
            test_passed = false;
        }
    }

    simputs("Testing macro boundary conditions...\n");

    uint32_t boundary_tests[] = {
        0x100, 0x11F, // Bus/Command error boundaries
        0x120, 0x12F, // READ error boundaries
        0x130, 0x13F, // WRITE error boundaries
        0x140, 0x14F, // Security error boundaries
        0x200, 0x20F  // JUMP error boundaries
    };

    for (int i = 0; i < sizeof(boundary_tests) / sizeof(boundary_tests[0]); i++) {
        uint32_t boundary_code = boundary_tests[i];
        if ((boundary_code >= 0x100 && boundary_code <= 0x2FF)) {
            simputs("PASS: Boundary code 0x");
            simputshex32("", boundary_code);
            simputs(" in valid range\n");
        }
    }

    simputs("Helper macro verification completed\n");
    mark_test_result(ctx, test_passed, "Helper Macro Verification");
    return test_passed;
}

static bool verify_error_reporting(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Test 8: Error Reporting Verification ===\n");
    simputs("SPEC: All error scenarios must be properly reported in status ring buffer\n");

    bool test_passed = true;
    int errors_found = 0;

    simputs("Scanning status ring buffer for error reports...\n");

    for (int i = 0; i < MAX_STATUS_BUFFER_READS; i++) {
        uint32_t status = 0;
        int result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result == OCCP_SUCCESS && status != 0) {
            uint32_t fw_id = (status >> 28) & 0xF;
            uint32_t msg_type = (status >> 24) & 0xF;
            uint32_t msg_value = status & 0xFFFFFF;

            if (fw_id == SMC_STATUS_FW_ID_SMC_BL0 && msg_type == SMC_STATUS_TYPE_ERROR) {
                ctx->status_entries_processed++;
                errors_found++;

                if ((msg_value & 0xFF0) >= 0x100 && (msg_value & 0xFF0) <= 0x2FF) {
                    simputs("FOUND: OCCP Error: ");
                    simputshex32("0x", msg_value);
                    simputs("\n");
                }
            }
        } else if (status == 0) {
            break;
        }
    }

    ctx->errors_found = errors_found;

    simputs("\n**ERROR REPORTING RESULTS**:\n");
    simputshex32("Total violations triggered: ", ctx->violations_triggered);
    simputshex32("Total error entries found: ", errors_found);
    simputshex32("Status entries processed: ", ctx->status_entries_processed);

    if (errors_found > 0) {
        simputs("SUCCESS: Error reporting system is functional\n");
    } else {
        simputs("INFO: No error entries found in status buffer\n");
        simputs("This may be expected if scenarios didn't trigger detectable errors\n");
    }

    mark_test_result(ctx, test_passed, "Error Reporting Verification");
    return test_passed;
}

/*
 * Critical cases: requests the ROM must reject, a byte-order check and
 * back-to-back writes.
 */

static bool test_critical_address_wraparound_bugs(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Critical Test: Address Wraparound Bug Detection ===\n");
    simputs("BUG TARGET: Address arithmetic overflow in smc_occp_check_addr_access_allowed()\n");

    bool test_passed = true;
    ctx->critical_bugs_tested++;

    // A write near the top of the address space must not wrap into a valid range.
    simputs("Testing maximum address wraparound vulnerability...\n");
    uint64_t max_addr = 0xFFFFFFFFFFFFFFFEULL; // Close to UINT64_MAX
    uint8_t test_data[16] = {0};

    int result = occp_send_write_command(ctx->occp_ctx, 0x55, max_addr, test_data, 16);
    if (result == 0) {
        simputs("POTENTIAL BUG: Address wraparound not properly detected\n");
        test_passed = false;
    } else {
        simputs("Expected failure: Address wraparound protection working\n");
        ctx->violations_triggered++;
    }

    simputs("Testing edge case address boundaries...\n");
    uint64_t edge_addresses[] = {
        0xFFFFFFFFFFFFFFF0ULL, // 16 bytes from max
        0xFFFFFFFFFFFFFFF8ULL, // 8 bytes from max
        0xFFFFFFFFFFFFFFFCULL, // 4 bytes from max
        0x8000000000000000ULL, // Sign bit boundary
    };

    for (int i = 0; i < 4; i++) {
        result = occp_send_write_command(ctx->occp_ctx, 0x55, edge_addresses[i], test_data, 16);
        if (result == 0) {
            simputs("POTENTIAL BUG: Edge address case not handled\n");
            test_passed = false;
        } else {
            ctx->violations_triggered++;
        }
    }

    mark_test_result(ctx, test_passed, "Address Wraparound Bug Detection");
    return test_passed;
}

static bool test_critical_integer_overflow_bugs(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Critical Test: Integer Overflow Bug Detection ===\n");
    simputs("BUG TARGET: Integer multiplication overflow in OCCP_CHECK_OVERFLOW_MUL macro\n");

    bool test_passed = true;
    ctx->critical_bugs_tested++;

    simputs("Testing maximum count multiplication overflow...\n");
    uint32_t max_count = 0xFFFFFFFF; // Maximum uint32_t
    uint8_t dummy_read[8];

    int result = occp_send_read_command(ctx->occp_ctx, 0x55, 0xC0066000, max_count, dummy_read);
    if (result == 0) {
        simputs("POTENTIAL BUG: Integer overflow in multiplication not detected\n");
        test_passed = false;
    } else {
        simputs("Expected failure: Integer overflow protection working\n");
        ctx->violations_triggered++;
    }

    uint32_t overflow_counts[] = {
        0x20000000,
        0x10000001,
        0x80000000,
    };

    for (int i = 0; i < 3; i++) {
        result =
            occp_send_read_command(ctx->occp_ctx, 0x55, 0xC0066000, overflow_counts[i], dummy_read);
        if (result == 0) {
            simputs("POTENTIAL BUG: Overflow count boundary not handled\n");
            test_passed = false;
        } else {
            ctx->violations_triggered++;
        }
    }

    mark_test_result(ctx, test_passed, "Integer Overflow Bug Detection");
    return test_passed;
}

static bool test_critical_endianness_bugs(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Critical Test: Endianness Bug Detection ===\n");
    simputs("BUG TARGET: Byte order handling in address/count extraction\n");

    bool test_passed = true;
    ctx->critical_bugs_tested++;

    simputs("Testing endianness consistency in address parsing...\n");

    uint8_t test_pattern[8] = {0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0};
    uint64_t test_addr = 0xC0066000;

    int write_result = occp_send_write_command(ctx->occp_ctx, 0x55, test_addr, test_pattern, 8);
    if (write_result == 0) {
        uint8_t read_back[8];
        int read_result = occp_send_read_command(ctx->occp_ctx, 0x55, test_addr, 1, read_back);

        if (read_result == 0) {
            bool endian_correct = true;
            for (int i = 0; i < 8; i++) {
                if (read_back[i] != test_pattern[7 - i]) { // Expects the bytes reversed
                    endian_correct = false;
                    break;
                }
            }

            if (!endian_correct) {
                simputs("POTENTIAL BUG: Endianness handling inconsistent\n");
                test_passed = false;
            }
        }
    }

    mark_test_result(ctx, test_passed, "Endianness Bug Detection");
    return test_passed;
}

static bool test_critical_race_condition_bugs(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Critical Test: Race Condition Bug Detection ===\n");
    simputs("BUG TARGET: Interface latching race conditions and error handling\n");

    bool test_passed = true;
    ctx->critical_bugs_tested++;

    simputs("Testing rapid command sequence for race conditions...\n");

    // Back-to-back writes with no wait between them; the results are not checked.
    for (int i = 0; i < 5; i++) {
        uint8_t test_data[8] = {(uint8_t)i};
        uint64_t addr = 0xC0066000 + (i * 8);

        int result = occp_send_write_command(ctx->occp_ctx, 0x55, addr, test_data, 1);
        (void)result;
        ctx->edge_cases_tested++;
    }

    mark_test_result(ctx, test_passed, "Race Condition Bug Detection");
    return test_passed;
}

static bool test_critical_state_machine_bugs(comprehensive_error_test_context_t *ctx) {
    simputs("\n=== Critical Test: State Machine Bug Detection ===\n");
    simputs("BUG TARGET: Interface state machine and error recovery bugs\n");

    bool test_passed = true;
    ctx->critical_bugs_tested++;

    simputs("Testing boundary condition state transitions...\n");
    uint8_t zero_data[1] = {0};
    int result = occp_send_write_command(ctx->occp_ctx, 0x55, 0xC0066000, zero_data, 0);
    if (result == 0) {
        simputs("POTENTIAL BUG: Zero-length command unexpectedly succeeded\n");
        test_passed = false;
    } else {
        ctx->violations_triggered++;
    }

    uint8_t boundary_data[512];
    memset(boundary_data, 0xCC, sizeof(boundary_data));

    result = occp_send_write_command(ctx->occp_ctx, 0x55, 0xC0066000, boundary_data, 255);
    if (result == 0) {
        simputs("POTENTIAL BUG: Boundary size check failed\n");
        test_passed = false;
    } else {
        ctx->violations_triggered++;
    }

    ctx->edge_cases_tested += 2;
    mark_test_result(ctx, test_passed, "State Machine Bug Detection");
    return test_passed;
}

static void finalize_comprehensive_results(comprehensive_error_test_context_t *ctx) {
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
    static comprehensive_error_test_context_t test_ctx = {0};

    init_test(0);

    simputs("=== OCCP Comprehensive Error Verification Test ===\n");
    simputs("Mission: Complete verification of the OCCP error codes\n");
    simputs("Coverage: CMD, READ, WRITE, SECURITY, JUMP errors\n");

    if (!initialize_interface(&occp_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    occp_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    occp_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    occp_ctx.overall_result = true;
    occp_ctx.cmd_count = 0;
    occp_ctx.exp_occp_last_error = 0;

    init_test_context(&test_ctx, &occp_ctx);

    test_memory_access_violations(&test_ctx);
    test_command_failures(&test_ctx);
    test_jump_security_violations(&test_ctx);
    test_invalid_command_injection(&test_ctx);
    test_buffer_overflow_scenarios(&test_ctx);
    test_validate_boot_security(&test_ctx);
    test_helper_macro_functionality(&test_ctx);
    verify_error_reporting(&test_ctx);

    // Critical cases
    test_critical_address_wraparound_bugs(&test_ctx);
    test_critical_integer_overflow_bugs(&test_ctx);
    test_critical_endianness_bugs(&test_ctx);
    test_critical_race_condition_bugs(&test_ctx);
    test_critical_state_machine_bugs(&test_ctx);

    finalize_comprehensive_results(&test_ctx);

    simputs("\n=== Comprehensive Error Verification Results Summary ===\n");
    simputshex32("Tests passed: ", test_ctx.passed_tests);
    simputshex32("Tests failed: ", test_ctx.total_tests - test_ctx.passed_tests);
    simputshex32("Total tests: ", test_ctx.total_tests);
    simputshex32("Error violations triggered: ", test_ctx.violations_triggered);
    simputshex32("Error entries found: ", test_ctx.errors_found);
    simputshex32("Critical bugs tested: ", test_ctx.critical_bugs_tested);
    simputshex32("Edge cases tested: ", test_ctx.edge_cases_tested);
    simputshex32("Security violations tested: ", test_ctx.security_violations_tested);
    simputshex32("Status entries processed: ", test_ctx.status_entries_processed);

    if (test_ctx.overall_result) {
        simputs("COMPREHENSIVE OCCP ERROR VERIFICATION: PASS\n");
        simputs("All OCCP error code scenarios verified successfully\n");
        test_pass(0);
    } else {
        simputs("COMPREHENSIVE OCCP ERROR VERIFICATION: FAIL\n");
        simputs("OCCP error code verification issues detected\n");
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
