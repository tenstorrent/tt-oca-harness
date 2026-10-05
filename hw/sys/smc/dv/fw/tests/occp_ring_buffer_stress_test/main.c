/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Stresses SMC status ring buffer head/tail movement through fill, wrap past capacity,
 * interleaved read/write and underflow, using ROM-reported OCCP errors as the entries.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

#include <string.h>

typedef struct {
    test_context_t *occp_ctx;
    int total_tests;
    int passed_tests;
    bool overall_result;
} ring_buffer_stress_ctx_t;

#define SMC_RING_BUFFER_SIZE 512
/* head == tail marks empty, so one slot always stays free. */
#define SMC_RING_BUFFER_CAPACITY (SMC_RING_BUFFER_SIZE - 1)
#define OCCP_ERROR_ACCESS_VIOLATION_CODE 0x02

typedef struct {
    uint16_t value;
    uint8_t msg_type;
} expected_entry_t;

static expected_entry_t expected_buffer[SMC_RING_BUFFER_SIZE];
static uint32_t expected_head;
static uint32_t expected_tail;
static uint32_t consecutive_failures;

#define ROM_PROTECTED_SRAM_BASE SMC_SRAM_BASE_ADDR

typedef enum {
    STATUS_OP_WRITE_UNALIGNED = 0,
    STATUS_OP_WRITE_PROTECTED,
    STATUS_OP_READ_PROTECTED,
    STATUS_OP_VALIDATE_BOOT
} status_op_t;

static inline uint16_t occp_error_with_nibble(uint16_t base_code, uint8_t nibble) {
    return (uint16_t)(base_code | ((uint16_t)(nibble & 0xF) << 8));
}

static inline uint16_t occp_error_with_data(uint16_t base_code, uint8_t data) {
    return (uint16_t)(base_code | (uint16_t)(data & 0xFF));
}

static void reset_expected_buffer(void) {
    expected_head = 0;
    expected_tail = 0;
    consecutive_failures = 0;
    memset(expected_buffer, 0, sizeof(expected_buffer));
}

static bool append_expected_entry(uint16_t value, uint8_t msg_type) {
    expected_buffer[expected_head].value = value;
    expected_buffer[expected_head].msg_type = msg_type;
    expected_head = (expected_head + 1) % SMC_RING_BUFFER_SIZE;
    if (expected_head == expected_tail) {
        expected_tail = (expected_tail + 1) % SMC_RING_BUFFER_SIZE;
    }
    simputshex32("APPENDED VALUE: ", value);
    simputshex32("EXPECTED HEAD: ", expected_head);
    simputshex32("EXPECTED TAIL: ", expected_tail);
    return true;
}

static bool fetch_smc_status(test_context_t *ctx, uint32_t *status_word) {
    uint32_t value = 0;
    int result = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &value);

    if (result != OCCP_SUCCESS) {
        simputshex32("ERROR: GET_SMC_STATUS failed with code ", result);
        return false;
    }

    *status_word = value;
    return true;
}

static bool drain_status_buffer(test_context_t *ctx) {
    uint32_t status = ~0u;
    while (true) {
        if (!fetch_smc_status(ctx, &status)) {
            return false;
        }
        if (status == 0) {
            break;
        }
    }
    return true;
}

static bool verify_empty_buffer(test_context_t *ctx) {
    uint32_t status = 0;
    if (!fetch_smc_status(ctx, &status)) {
        return false;
    }

    if (status != 0) {
        simputshex32("ERROR: Expected empty buffer (status) ", status);
        return false;
    } else {
        simputs("PASS: Empty buffer\n");
    }

    return true;
}

static bool drain_and_verify_expected(test_context_t *ctx, uint32_t expected_count,
                                      bool require_empty_after) {
    bool result = true;
    for (uint32_t i = 0; i < expected_count; i++) {
        uint32_t status = 0;
        if (!fetch_smc_status(ctx, &status)) {
            result = false;
        }

        if (status == 0) {
            simputshex32("ERROR: Missing status entry at index ", i);
            result = false;
        }

        uint32_t msg_type = (status >> 24) & 0xFF;
        uint32_t fw_id = (status >> 16) & 0xFF;
        uint32_t msg_value = status & 0xFFFF;
        expected_entry_t entry = expected_buffer[expected_tail];
        expected_tail = (expected_tail + 1) % SMC_RING_BUFFER_SIZE;

        simputshex32("EXPECTED HEAD: ", expected_head);
        simputshex32("EXPECTED TAIL: ", expected_tail);
        simputshex32("EXPECTED STATUS: ", entry.value);
        simputshex32("RECEIVED STATUS: ", msg_value);

        if (msg_type != entry.msg_type) {
            simputshex32("ERROR: Unexpected message type ", msg_type);
            simputshex32("EXPECTED TYPE: ", entry.msg_type);
            result = false;
        }

        if (fw_id != OCCP_FW_ID_SMC_BL0) {
            simputshex32("ERROR: Unexpected firmware ID ", fw_id);
            result = false;
        }

        if (msg_value != entry.value) {
            simputshex32("ERROR: Expected status value ", entry.value);
            simputshex32("ERROR: Actual status value ", msg_value);
            result = false;
        }
    }

    if (require_empty_after && !verify_empty_buffer(ctx)) {
        result = false;
    }

    return result;
}

static bool issue_unaligned_write(test_context_t *ctx, uint16_t *expected_value) {
    uint8_t data[4] = {0};
    uint64_t addr = OCCP_TEST_BASE_ADDR + 1;
    int result = occp_send_write_command(ctx, ctx->slave_addr, addr, data, sizeof(data));

    if (result == OCCP_SUCCESS) {
        simputs("ERROR: Expected write command to fail (unaligned)\n");
        return false;
    }

    *expected_value = OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED;
    return true;
}

static bool issue_protected_write(test_context_t *ctx, uint16_t *expected_value) {
    uint8_t data[8] = {0};
    uint64_t addr = ROM_PROTECTED_SRAM_BASE;
    int result = occp_send_write_command(ctx, ctx->slave_addr, addr, data, sizeof(data));

    if (result == OCCP_SUCCESS) {
        simputs("ERROR: Expected protected write command to fail\n");
        return false;
    }

    *expected_value = occp_error_with_nibble(OCCP_SPEC_ERROR_WRITE_ACCESS_DENIED,
                                             OCCP_ERROR_ACCESS_VIOLATION_CODE);
    return true;
}

static bool issue_protected_read(test_context_t *ctx, uint16_t *expected_value) {
    uint8_t rx_buf[4];
    uint64_t addr = ROM_PROTECTED_SRAM_BASE;
    int result = occp_send_read_command(ctx, ctx->slave_addr, addr, rx_buf, sizeof(rx_buf));

    if (result == OCCP_SUCCESS) {
        simputs("ERROR: Expected protected read command to fail\n");
        return false;
    }

    *expected_value = occp_error_with_nibble(OCCP_SPEC_ERROR_READ_ACCESS_DENIED,
                                             OCCP_ERROR_ACCESS_VIOLATION_CODE);
    return true;
}

static bool issue_validate_boot_invalid(test_context_t *ctx, uint16_t *expected_value) {
    int result = occp_send_validate_boot_command(ctx, ctx->slave_addr, 0xFFFFFFFFFFFFFFFFULL);
    if (result == OCCP_SUCCESS) {
        simputs("ERROR: Expected VALIDATE_BOOT to fail for invalid address\n");
        return false;
    }

    *expected_value = OCCP_SPEC_ERROR_VALIDATE_ADDRESS_FAILED;
    return true;
}

static bool generate_status_entries(test_context_t *ctx, uint32_t desired_entries) {
    int entries_generated = 0;
    const status_op_t pattern[] = {STATUS_OP_WRITE_UNALIGNED, STATUS_OP_WRITE_PROTECTED,
                                   STATUS_OP_READ_PROTECTED, STATUS_OP_VALIDATE_BOOT};
    uint32_t command_index = get_random_int() % 4;

    while (entries_generated < desired_entries) {
        status_op_t op = pattern[command_index];
        uint16_t expected_value = 0;
        bool success = false;

        switch (op) {
        case STATUS_OP_WRITE_UNALIGNED:
            success = issue_unaligned_write(ctx, &expected_value);
            break;
        case STATUS_OP_WRITE_PROTECTED:
            success = issue_protected_write(ctx, &expected_value);
            break;
        case STATUS_OP_READ_PROTECTED:
            success = issue_protected_read(ctx, &expected_value);
            break;
        case STATUS_OP_VALIDATE_BOOT:
            success = issue_validate_boot_invalid(ctx, &expected_value);
            break;
        default:
            success = false;
            break;
        }

        if (!success) {
            return false;
        }

        if (!append_expected_entry(expected_value, OCCP_STATUS_MSG_ERROR)) {
            return false;
        }
        entries_generated++;

        uint16_t cmd_failed =
            occp_error_with_data(OCCP_SPEC_ERROR_CMD_FAILED, OCCP_ERROR_ACCESS_VIOLATION_CODE);
        if (!append_expected_entry(cmd_failed, OCCP_STATUS_MSG_ERROR)) {
            return false;
        }
        entries_generated++;

        consecutive_failures++;
        if (consecutive_failures >= 4) {
            // A valid command clears the ROM's consecutive-error count; five errors unlatch it.
            uint32_t value = 0;
            int result = occp_send_get_version_command(ctx, ctx->slave_addr, &value);
            if (result != OCCP_SUCCESS) {
                return false;
            }
            consecutive_failures = 0;
        }
    }

    return true;
}

static uint32_t expected_length(void) {
    uint32_t length;
    if (expected_head >= expected_tail) {
        length = expected_head - expected_tail;
    } else {
        length = expected_head + SMC_RING_BUFFER_SIZE - expected_tail;
    }
    return length;
}

static void record_test_result(ring_buffer_stress_ctx_t *ctx, bool passed, const char *name) {
    ctx->total_tests++;
    if (passed) {
        ctx->passed_tests++;
        simputs("PASS: ");
    } else {
        ctx->overall_result = false;
        simputs("FAIL: ");
    }

    simputs(name);
    simputs("\n");
}

static bool test_fill_and_drain(ring_buffer_stress_ctx_t *ctx) {
    simputs("\n=== Test 1: Fill and Drain ===\n");

    if (!drain_status_buffer(ctx->occp_ctx)) {
        return false;
    }

    const uint32_t desired_entries = 32;

    consecutive_failures = 0;
    if (!generate_status_entries(ctx->occp_ctx, desired_entries)) {
        return false;
    }

    simputshex32("Expected log length before drain: ", expected_length());

    return drain_and_verify_expected(ctx->occp_ctx, expected_length(), true);
}

static bool test_full_capacity_wrap(ring_buffer_stress_ctx_t *ctx) {
    simputs("\n=== Test 2: Full Capacity Wrap ===\n");

    if (!drain_status_buffer(ctx->occp_ctx)) {
        return false;
    }

    const uint32_t extra_entries = 10;
    const uint32_t total_entries = SMC_RING_BUFFER_CAPACITY + extra_entries;

    consecutive_failures = 0;
    if (!generate_status_entries(ctx->occp_ctx, total_entries)) {
        return false;
    }

    simputshex32("Expected log length after wrap drop: ", expected_length());

    return drain_and_verify_expected(ctx->occp_ctx, expected_length(), true);
}

static bool test_interleaved_read_write(ring_buffer_stress_ctx_t *ctx) {
    simputs("\n=== Test 3: Interleaved Read/Write ===\n");

    if (!drain_status_buffer(ctx->occp_ctx)) {
        return false;
    }

    const uint32_t first_chunk_entries = 160;
    const uint32_t read_during_entries = 60;
    const uint32_t second_chunk_entries = 200;

    consecutive_failures = 0;
    if (!generate_status_entries(ctx->occp_ctx, first_chunk_entries)) {
        return false;
    }

    simputshex32("Expected entries before mid-drain: ", expected_length());

    if (!drain_and_verify_expected(ctx->occp_ctx, read_during_entries, false)) {
        return false;
    }

    consecutive_failures = 0;

    if (!generate_status_entries(ctx->occp_ctx, second_chunk_entries)) {
        return false;
    }

    simputshex32("Expected entries before final drain: ", expected_length());

    return drain_and_verify_expected(ctx->occp_ctx, expected_length(), true);
}

static bool test_underflow_behavior(ring_buffer_stress_ctx_t *ctx) {
    simputs("\n=== Test 4: Underflow Handling ===\n");

    if (!drain_status_buffer(ctx->occp_ctx)) {
        return false;
    }

    return verify_empty_buffer(ctx->occp_ctx);
}

static void run_test_suite(ring_buffer_stress_ctx_t *ctx) {
    simputs("\n=== OCCP Ring Buffer Stress Suite ===\n");
    ctx->overall_result = true;
    ctx->total_tests = 0;
    ctx->passed_tests = 0;

    record_test_result(ctx, test_fill_and_drain(ctx), "Fill and Drain");
    record_test_result(ctx, test_full_capacity_wrap(ctx), "Full Capacity Wrap");
    record_test_result(ctx, test_interleaved_read_write(ctx), "Interleaved Read/Write");
    record_test_result(ctx, test_underflow_behavior(ctx), "Underflow Handling");

    simputs("\n=== Stress Test Summary ===\n");
    simputshex32("Tests passed: ", ctx->passed_tests);
    simputshex32("Tests fa1led: ", ctx->total_tests - ctx->passed_tests);
}

int main(void) {
    static test_context_t occp_ctx = {0};
    static ring_buffer_stress_ctx_t stress_ctx = {0};

    init_test(0);

    simputs("=== OCCP Ring Buffer Stress Test ===\n");

    if (!initialize_interface(&occp_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    occp_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    occp_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    occp_ctx.overall_result = true;

    memset(&stress_ctx, 0, sizeof(stress_ctx));
    stress_ctx.occp_ctx = &occp_ctx;
    stress_ctx.overall_result = true;

    reset_expected_buffer();

    run_test_suite(&stress_ctx);

    if (stress_ctx.overall_result) {
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
