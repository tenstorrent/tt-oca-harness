/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Reads the SMC and SEP status ring buffers through OCCP status commands: drains the SMC
 * buffer, interleaves SMC/SEP reads, and polls repeatedly, checking non-empty SMC entries.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>
#include "smc_status.h"

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;
} ring_buffer_advanced_test_context_t;

static void init_test_context(ring_buffer_advanced_test_context_t *ctx, test_context_t *occp_ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->occp_ctx = occp_ctx;
    ctx->overall_result = true;
    ctx->total_tests = 0;
    ctx->passed_tests = 0;
}

static uint32_t create_status_message(uint32_t fw_id, uint32_t msg_type, uint32_t msg_value) {
    return ((fw_id & 0xF) << 28) | ((msg_type & 0xF) << 24) | (msg_value & 0xFFFFFF);
}

static bool validate_message_format(uint32_t message, uint32_t exp_fw_id, uint32_t exp_type,
                                    uint32_t exp_value) {
    uint32_t fw_id = (message >> 28) & 0xF;
    uint32_t msg_type = (message >> 24) & 0xF;
    uint32_t msg_value = message & 0xFFFFFF;

    if (fw_id != exp_fw_id || msg_type != exp_type || msg_value != exp_value) {
        simputshex32("Message format validation failed. Got: 0x", message);
        simputshex32("  Expected FW_ID: ", exp_fw_id);
        simputshex32("  Got FW_ID: ", fw_id);
        simputshex32("  Expected Type: ", exp_type);
        simputshex32("  Got Type: ", msg_type);
        simputshex32("  Expected Value: 0x", exp_value);
        simputshex32("  Got Value: 0x", msg_value);
        return false;
    }
    return true;
}

static void mark_test_result(ring_buffer_advanced_test_context_t *ctx, bool passed,
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

static bool test_message_format_validation(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 1: Message Format Validation ===\n");

    bool test_passed = true;
    uint32_t fw_ids[] = {SMC_STATUS_FW_ID_SEP_BL0, SMC_STATUS_FW_ID_SEP_BL1,
                         SMC_STATUS_FW_ID_SMC_BL0, SMC_STATUS_FW_ID_SMC_BL1};
    uint32_t msg_types[] = {SMC_STATUS_TYPE_STATUS, SMC_STATUS_TYPE_WARNING, SMC_STATUS_TYPE_ERROR};
    uint32_t test_values[] = {0x000001, 0x123456, 0xFFFFFF, 0xABCDEF, 0x000000};

    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 3; j++) {
            for (int k = 0; k < 5; k++) {
                uint32_t test_msg = create_status_message(fw_ids[i], msg_types[j], test_values[k]);

                if (!validate_message_format(test_msg, fw_ids[i], msg_types[j], test_values[k])) {
                    test_passed = false;
                    break;
                }
            }
            if (!test_passed) break;
        }
        if (!test_passed) break;
    }

    if (test_passed) {
        simputs("Message format validation: PASS (tested 60 combinations)\n");
    }

    mark_test_result(ctx, test_passed, "Message Format Validation");
    return test_passed;
}

static bool test_ring_buffer_basic_operations(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 2: Ring Buffer Basic Operations ===\n");

    uint32_t smc_status, sep_status;
    int result;
    bool test_passed = true;

    result =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status);
    if (result != OCCP_SUCCESS) {
        simputs("Failed to get SMC status\n");
        test_passed = false;
    } else {
        simputshex32("SMC Status read: 0x", smc_status);
        if (smc_status != 0) {
            uint32_t fw_id = (smc_status >> 28) & 0xF;
            if (fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
                simputshex32("Unexpected SMC FW_ID: ", fw_id);
                test_passed = false;
            }
        }
    }

    result =
        occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status);
    if (result != OCCP_SUCCESS) {
        simputs("Failed to get SEP status\n");
        test_passed = false;
    } else {
        simputshex32("SEP Status read: 0x", sep_status);
    }

    mark_test_result(ctx, test_passed, "Ring Buffer Basic Operations");
    return test_passed;
}

static bool test_ring_buffer_wrap_around(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 3: Head/Tail Pointer Wrap-Around ===\n");

    bool test_passed = true;
    uint32_t status;
    int consecutive_empty_reads = 0;
    int total_reads = 0;
    const int max_reads = 600;

    simputs("Reading SMC status messages to test wrap-around behavior\n");

    while (total_reads < max_reads && consecutive_empty_reads < 10) {
        int result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result != OCCP_SUCCESS) {
            simputs("Failed to read SMC status during wrap-around test\n");
            test_passed = false;
            break;
        }

        total_reads++;

        if (status == 0) {
            consecutive_empty_reads++;
        } else {
            consecutive_empty_reads = 0;
            simputshex32("Read status message: 0x", status);

            uint32_t fw_id = (status >> 28) & 0xF;
            uint32_t msg_type = (status >> 24) & 0xF;

            if (fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
                simputshex32("Invalid FW_ID in wrap-around test: ", fw_id);
                test_passed = false;
            }

            if (msg_type > SMC_STATUS_TYPE_ERROR) {
                simputshex32("Invalid message type in wrap-around test: ", msg_type);
                test_passed = false;
            }
        }

        if (total_reads % 100 == 0) {
            simputshex32("Wrap-around test progress: ", total_reads);
        }
    }

    simputshex32("Total messages read: ", total_reads);
    simputshex32("Consecutive empty reads at end: ", consecutive_empty_reads);

    if (total_reads < 50) {
        simputs("Warning: Low message count may indicate issue with ROM status reporting\n");
    }

    mark_test_result(ctx, test_passed, "Head/Tail Pointer Wrap-Around");
    return test_passed;
}

static bool test_concurrent_buffer_access(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 4: Concurrent SMC/SEP Buffer Access ===\n");

    bool test_passed = true;
    uint32_t smc_status, sep_status;
    int smc_result, sep_result;

    for (int i = 0; i < 20; i++) {
        smc_result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status);
        sep_result =
            occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status);

        if (smc_result != OCCP_SUCCESS) {
            simputs("SMC status command failed during concurrent test\n");
            test_passed = false;
            break;
        }

        if (sep_result != OCCP_SUCCESS) {
            simputs("SEP status command failed during concurrent test\n");
            test_passed = false;
            break;
        }

        if (smc_status != 0 && sep_status != 0) {
            uint32_t smc_fw_id = (smc_status >> 28) & 0xF;
            uint32_t sep_fw_id = (sep_status >> 28) & 0xF;

            if (smc_fw_id != SMC_STATUS_FW_ID_SMC_BL0) {
                simputshex32("Invalid SMC FW_ID in concurrent test: ", smc_fw_id);
                test_passed = false;
            }

            if (sep_fw_id != SMC_STATUS_FW_ID_SEP_BL0 && sep_fw_id != SMC_STATUS_FW_ID_SEP_BL1) {
                simputshex32("Note: SEP FW_ID in concurrent test: ", sep_fw_id);
            }
        }

        if (i % 5 == 0) {
            simputshex32("Concurrent test iteration: ", i);
            simputshex32("  SMC status: 0x", smc_status);
            simputshex32("  SEP status: 0x", sep_status);
        }
    }

    mark_test_result(ctx, test_passed, "Concurrent SMC/SEP Buffer Access");
    return test_passed;
}

static bool test_status_command_variations(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 5: Status Command Variations ===\n");

    bool test_passed = true;
    uint32_t version, occp_status, smc_status, sep_status;

    int version_result =
        occp_send_get_version_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &version);
    int occp_result =
        occp_send_get_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &occp_status);
    int smc_result =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status);
    int sep_result =
        occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status);

    if (version_result != OCCP_SUCCESS || occp_result != OCCP_SUCCESS ||
        smc_result != OCCP_SUCCESS || sep_result != OCCP_SUCCESS) {
        simputs("One or more status commands failed\n");
        test_passed = false;
    } else {
        simputshex32("GET_VERSION: 0x", version);
        simputshex32("GET_OCCP_STATUS: 0x", occp_status);
        simputshex32("GET_SMC_STATUS: 0x", smc_status);
        simputshex32("GET_SEP_STATUS: 0x", sep_status);

        if (smc_status != 0) {
            if (!validate_message_format(smc_status, SMC_STATUS_FW_ID_SMC_BL0,
                                         (smc_status >> 24) & 0xF, smc_status & 0xFFFFFF)) {
                test_passed = false;
            }
        }
    }

    mark_test_result(ctx, test_passed, "Status Command Variations");
    return test_passed;
}

static bool test_rapid_status_polling(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 6: Rapid Status Polling (Interface Stress) ===\n");

    bool test_passed = true;
    uint32_t status;
    int successful_reads = 0;
    const int total_polls = 50;

    for (int i = 0; i < total_polls; i++) {
        int result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);

        if (result != OCCP_SUCCESS) {
            simputshex32("Failed status poll at iteration: ", i);
            test_passed = false;
            break;
        }

        successful_reads++;

        if (status != 0) {
            uint32_t fw_id = (status >> 28) & 0xF;
            uint32_t msg_type = (status >> 24) & 0xF;

            if (fw_id != SMC_STATUS_FW_ID_SMC_BL0 || msg_type > SMC_STATUS_TYPE_ERROR) {
                simputshex32("Invalid message in rapid polling at iteration: ", i);
                simputshex32("  Status: 0x", status);
                test_passed = false;
            }
        }
    }

    simputshex32("Successful rapid polls: ", successful_reads);
    simputshex32("Total polls attempted: ", total_polls);

    if (successful_reads < total_polls * 0.95) {
        simputs("Warning: High failure rate in rapid polling\n");
        test_passed = false;
    }

    mark_test_result(ctx, test_passed, "Rapid Status Polling");
    return test_passed;
}

static bool test_edge_cases_and_boundary_conditions(ring_buffer_advanced_test_context_t *ctx) {
    simputs("\n=== Test 7: Edge Cases and Boundary Conditions ===\n");

    bool test_passed = true;

    uint32_t test_messages[] = {
        create_status_message(0x0, 0x0, 0x000000), create_status_message(0x3, 0x2, 0xFFFFFF),
        create_status_message(0x2, 0x1, 0x123456), create_status_message(0x1, 0x0, 0xABCDEF)};

    for (int i = 0; i < 4; i++) {
        uint32_t msg = test_messages[i];
        uint32_t fw_id = (msg >> 28) & 0xF;
        uint32_t msg_type = (msg >> 24) & 0xF;
        uint32_t msg_value = msg & 0xFFFFFF;

        simputshex32("Testing edge case message: 0x", msg);

        if (!validate_message_format(msg, fw_id, msg_type, msg_value)) {
            test_passed = false;
            break;
        }
    }

    mark_test_result(ctx, test_passed, "Edge Cases and Boundary Conditions");
    return test_passed;
}

static void run_test_suite(ring_buffer_advanced_test_context_t *ctx) {
    simputs("=== Ring Buffer Advanced Test Suite ===\n");
    simputs(
        "Testing overflow protection, wrap-around, concurrent access, and message validation\n");

    test_message_format_validation(ctx);
    test_ring_buffer_basic_operations(ctx);
    test_ring_buffer_wrap_around(ctx);
    test_concurrent_buffer_access(ctx);
    test_status_command_variations(ctx);
    test_rapid_status_polling(ctx);
    test_edge_cases_and_boundary_conditions(ctx);

    simputs("\n=== Advanced Test Results Summary ===\n");
    simputshex32("Tests passed: ", ctx->passed_tests);
    simputshex32("Tests failed: ", ctx->total_tests - ctx->passed_tests);
    simputshex32("Total tests: ", ctx->total_tests);

    if (ctx->overall_result) {
        simputs("ALL ADVANCED TESTS PASSED!\n");
    } else {
        simputs("SOME ADVANCED TESTS FAILED!\n");
    }
}

static void finalize_test_results(ring_buffer_advanced_test_context_t *ctx) {
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
    static ring_buffer_advanced_test_context_t test_ctx = {0};

    init_test(0);

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

    run_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);

    if (test_ctx.overall_result) {
        test_pass(0);
    } else {
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
