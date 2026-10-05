/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Reads the SMC and SEP status ring buffers through OCCP status commands: checks the first
 * SMC boot entry, that the SEP buffer is empty, and the firmware ID of later SMC entries.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>

typedef struct {
    test_context_t *occp_ctx;
    uint32_t test_messages[20];
    int test_count;
    bool overall_result;
} ring_buffer_test_context_t;

static void init_test_context(ring_buffer_test_context_t *ctx, test_context_t *occp_ctx) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->occp_ctx = occp_ctx;
    ctx->overall_result = true;
    ctx->test_count = 0;
}

static uint32_t create_test_message(uint32_t fw_id, uint32_t msg_type, uint32_t msg_value) {
    return ((fw_id & 0xF) << 28) | ((msg_type & 0xF) << 24) | (msg_value & 0xFFFFFF);
}

static bool verify_message_format(uint32_t message, uint32_t exp_fw_id, uint32_t exp_type,
                                  uint32_t exp_value) {
    uint32_t fw_id = (message >> 28) & 0xF;
    uint32_t msg_type = (message >> 24) & 0xF;
    uint32_t msg_value = message & 0xFFFFFF;

    if (fw_id != exp_fw_id || msg_type != exp_type || msg_value != exp_value) {
        simputs("Message format mismatch:\n");
        simputshex32("  Got:      0x", message);
        simputshex32("  FW ID:    ", fw_id);
        simputshex32("  Type:     ", msg_type);
        simputshex32("  Value:    0x", msg_value);
        return false;
    }
    return true;
}

static bool test_buffer_initialization(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 1: Buffer Initialization ===\n");

    uint32_t status;
    int result =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: Could not read SMC status\n");
        return false;
    }

    uint32_t expected_smc_init = 0x20000001;
    if (status != expected_smc_init) {
        simputshex32("FAIL: Expected SMC init status 0x", expected_smc_init);
        simputshex32(", got 0x", status);
        simputs("\n");
        return false;
    }

    simputs("PASS: SMC buffer contains expected initialization message\n");

    // The SEP ROM does not run in this bench, so its buffer stays empty.
    result = occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: Could not read SEP status\n");
        return false;
    }

    if (status != 0) {
        simputshex32("FAIL: SEP buffer should be empty, got 0x", status);
        simputs("\n");
        return false;
    }

    simputs("PASS: SEP buffer is empty as expected\n");
    simputs("PASS: Buffer initialization\n");
    return true;
}

static bool test_message_format_validation(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 2: Message Format Validation ===\n");

    uint32_t fw_ids[] = {0x0, 0x1, 0x2, 0x3};
    uint32_t msg_types[] = {0x0, 0x1, 0x2};
    uint32_t test_values[] = {0x000001, 0x123456, 0xFFFFFF};

    int test_idx = 0;
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 3; j++) {
            for (int k = 0; k < 3; k++) {
                uint32_t test_msg = create_test_message(fw_ids[i], msg_types[j], test_values[k]);
                ctx->test_messages[test_idx++] = test_msg;

                if (!verify_message_format(test_msg, fw_ids[i], msg_types[j], test_values[k])) {
                    simputs("FAIL: Message format validation failed\n");
                    return false;
                }
            }
        }
    }
    ctx->test_count = test_idx;

    simputs("PASS: Message format validation\n");
    return true;
}

static bool test_basic_operations(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 3: Basic OCCP Status Commands ===\n");

    uint32_t occp_status;
    int result =
        occp_send_get_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &occp_status);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: GET_OCCP_STATUS command failed\n");
        return false;
    }
    simputshex32("OCCP Status: 0x", occp_status);

    uint32_t smc_status;
    result =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: GET_SMC_STATUS command failed\n");
        return false;
    }
    simputshex32("SMC Status (next message): 0x", smc_status);

    uint32_t sep_status;
    result =
        occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: GET_SEP_STATUS command failed\n");
        return false;
    }
    simputshex32("SEP Status: 0x", sep_status);

    simputs("PASS: Basic OCCP status commands\n");
    return true;
}

static bool test_occp_command_variations(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 4: OCCP Command Variations ===\n");

    uint32_t version;
    int result = occp_send_get_version_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &version);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: GET_VERSION command failed\n");
        return false;
    }
    simputshex32("ROM Version: 0x", version);

    for (int i = 0; i < 5; i++) {
        uint32_t status;
        result =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &status);
        if (result != OCCP_SUCCESS) {
            simputs("FAIL: Multiple SMC status calls failed\n");
            return false;
        }
        simputshex32("INFO: SMC status (iteration ", i);
        simputshex32("): 0x", status);

        if (status != 0) {
            uint32_t fw_id = (status >> 28) & 0xF;
            uint32_t msg_type = (status >> 24) & 0xF;

            if (fw_id != 0x2) {
                simputshex32("FAIL: Expected FW_ID 0x2, got 0x", fw_id);
                return false;
            }

            if (msg_type > 2) {
                simputshex32("FAIL: Invalid message type 0x", msg_type);
                return false;
            }
        }
    }

    simputs("PASS: OCCP command variations\n");
    return true;
}

static bool test_interface_robustness(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 5: Interface Robustness ===\n");

    for (int i = 0; i < 10; i++) {
        uint32_t smc_status, sep_status, occp_status;

        int result1 =
            occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status);
        int result2 =
            occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status);
        int result3 =
            occp_send_get_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &occp_status);

        if (result1 != OCCP_SUCCESS || result2 != OCCP_SUCCESS || result3 != OCCP_SUCCESS) {
            simputshex32("FAIL: Command failed at iteration ", i);
            return false;
        }

        if (smc_status != 0) {
            simputshex32("INFO: SMC status at iteration ", i);
            simputshex32("      Value: 0x", smc_status);

            uint32_t fw_id = (smc_status >> 28) & 0xF;
            if (fw_id != 0x2) {
                simputshex32("FAIL: Invalid FW_ID 0x", fw_id);
                return false;
            }
        }
    }

    simputs("PASS: Interface robustness\n");
    return true;
}

static bool test_command_consistency(ring_buffer_test_context_t *ctx) {
    simputs("\n=== Test 6: Command Consistency ===\n");

    uint32_t smc_status1, smc_status2;
    uint32_t sep_status1, sep_status2;

    int result1 =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status1);
    int result2 =
        occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status1);

    if (result1 != OCCP_SUCCESS || result2 != OCCP_SUCCESS) {
        simputs("FAIL: First set of status commands failed\n");
        return false;
    }

    result1 =
        occp_send_get_smc_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &smc_status2);
    result2 =
        occp_send_get_sep_status_command(ctx->occp_ctx, ctx->occp_ctx->slave_addr, &sep_status2);

    if (result1 != OCCP_SUCCESS || result2 != OCCP_SUCCESS) {
        simputs("FAIL: Second set of status commands failed\n");
        return false;
    }

    simputshex32("SMC Status 1: 0x", smc_status1);
    simputshex32("SMC Status 2: 0x", smc_status2);
    simputshex32("SEP Status 1: 0x", sep_status1);
    simputshex32("SEP Status 2: 0x", sep_status2);

    simputs("PASS: Command consistency\n");
    return true;
}

static void run_test_suite(ring_buffer_test_context_t *ctx) {
    simputs("=== Ring Buffer Core Functionality Test Suite ===\n");

    bool results[] = {test_buffer_initialization(ctx), test_message_format_validation(ctx),
                      test_basic_operations(ctx),      test_occp_command_variations(ctx),
                      test_interface_robustness(ctx),  test_command_consistency(ctx)};

    int passed = 0;
    for (int i = 0; i < 6; i++) {
        if (results[i])
            passed++;
        else
            ctx->overall_result = false;
    }

    simputs("\n=== Test Results Summary ===\n");
    simputshex32("Tests passed: ", passed);
    simputshex32("Tests failed: ", 6 - passed);

    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
    } else {
        simputs("SOME TESTS FAILED!\n");
    }
}

static void finalize_test_results(ring_buffer_test_context_t *ctx) {
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
    static ring_buffer_test_context_t test_ctx = {0};

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
