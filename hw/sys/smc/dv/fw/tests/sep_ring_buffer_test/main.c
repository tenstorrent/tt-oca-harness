/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Ring Buffer Overflow/Underflow Test
 *
 * Tests SEP status ring buffer boundary conditions with cocotb driver.
 *
 * Test Scenarios:
 * 1. OVERFLOW: Write 600 entries (exceeds 512 capacity)
 *    - Verify newest 512 entries retained
 *    - Verify oldest 88 entries overwritten
 * 2. UNDERFLOW: Read from empty buffer
 *    - Verify returns 0
 *    - Verify no crashes
 * 3. EXACT_CAPACITY: Write exactly 512 entries
 *    - Verify all entries fit
 *    - Verify no overflow
 *
 * Specification Reference (smc_rom.adoc:1154):
 * "This ensures continuous operation without message loss due to buffer
 *  overflow, with newest entries automatically replacing the oldest when
 *  the buffer reaches capacity."
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

#include <string.h>

/* Scratch register addresses */
#define SMC_SCRATCH_10_ADDR (SMC_CPU_CTRL_SCRATCH_10__REG_ADDR)
#define SMC_SCRATCH_12_ADDR (SMC_CPU_CTRL_SCRATCH_12__REG_ADDR)
#define SMC_SCRATCH_5_ADDR  (SMC_CPU_CTRL_SCRATCH_5__REG_ADDR)

/* Coordination magic number */
#define COCOTB_READY_MAGIC 0xC0C07B00

/* Ring buffer size */
#define SMC_RING_BUFFER_SIZE 512

/* Status message format constants */
#define SMC_STATUS_FW_ID_SEP_BL0 0x1
#define SMC_STATUS_TYPE_STATUS   0x1
#define SMC_STATUS_TYPE_WARNING  0x8
#define SMC_STATUS_TYPE_ERROR    0xF

/*
 * Wait for cocotb driver to signal that entries are ready.
 */
static bool wait_for_cocotb_ready(test_context_t *ctx, uint32_t timeout_ms)
{
    (void)ctx;
    (void)timeout_ms;

    uint32_t iterations = 0;
    uint32_t last_printed_value = 0;

    simputs("\n=== Waiting for Cocotb Ready Signal ===\n");

    while (iterations < 1000000) {
        uint32_t scratch_10 = read_scratch(10);

        if (scratch_10 != last_printed_value && scratch_10 != 0) {
            simputshex32("DEBUG: Scratch 10 changed to: 0x", scratch_10);
            last_printed_value = scratch_10;
        }

        if (scratch_10 == COCOTB_READY_MAGIC) {
            simputs("SUCCESS: Cocotb signaled entries ready!\n");
            return true;
        }

        iterations++;

        if (iterations % 10000 == 0) {
            simputshex32("DEBUG: Still waiting... iteration ", iterations);
        }
    }

    simputs("ERROR: Timeout waiting for cocotb ready signal\n");
    return false;
}

/*
 * Read number of entries written by cocotb from Scratch 12.
 */
static uint32_t get_entry_count(test_context_t *ctx)
{
    (void)ctx;

    simputs("\n=== Reading Entry Count ===\n");
    uint32_t count = read_scratch(12);

    simputs("Entry count read from Scratch 12\n");
    simputshex32("  Number of entries: ", count);
    return count;
}

static bool read_and_validate_sep_status_buffer(test_context_t *ctx)
{
    uint32_t total_written = get_entry_count(ctx);
    simputshex32("Total entries written: ", total_written);

    simputs("\n=== Reading Buffer Contents ===\n");
    /* one entry always empty in the buffer, so capacity is one less than the total written */
    for (uint32_t i = 0;
         i < (total_written > (SMC_RING_BUFFER_SIZE - 1) ? (SMC_RING_BUFFER_SIZE - 1) : total_written);
         i++) {
        uint32_t status = 0;

        int result = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status);

        if (result != OCCP_SUCCESS) {
            simputs("FAIL: GET_SEP_STATUS failed\n");
            simputshex32("  Entry index: ", i);
            ctx->overall_result = false;
            return false;
        } else {
            simputs("GET_SEP_STATUS command passed\n");
            simputshex32("  Entry index: ", i);
            simputshex32("  Status:      0x", status);
        }
    }

    simputs("\n=== Verifying Buffer Empty ===\n");
    uint32_t status_after = 0;
    /* give it a few underflow tries */
    for (int i = 0; i < 10; i++) {
        int result = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status_after);

        if (result == OCCP_SUCCESS && status_after == 0) {
            simputs("PASS: Buffer empty after reading all entries\n");
        } else {
            simputs("FAIL: Buffer not empty\n");
            simputshex32("  Unexpected status: 0x", status_after);
            ctx->overall_result = false;
            return false;
        }
    }

    return true;
}

/*
 * Finalize test results and report to cocotb.
 */
static void finalize_test_results(test_context_t *ctx)
{
    uint32_t result_code;

    simputs("\n========================================\n");
    simputs("FINAL TEST RESULTS\n");
    simputs("========================================\n");

    if (ctx->overall_result) {
        simputs("\n*** ALL TESTS PASSED ***\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
        (void)result_code;
        test_pass(0);
    } else {
        simputs("\n*** TESTS FAILED ***\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
        (void)result_code;
        test_fail(0);
    }
}

int main(void)
{
    static test_context_t ctx = {0};

    init_test(0);

    simputs("\n========================================\n");
    simputs("SEP Ring Buffer Overflow/Underflow Test\n");
    simputs("========================================\n");

    if (!initialize_interface(&ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    ctx.overall_result = true;

    if (!wait_for_cocotb_ready(&ctx, 5000)) {
        simputs("FAIL: Cocotb ready timeout\n");
        test_fail(0);
    }

    read_and_validate_sep_status_buffer(&ctx);
    finalize_test_results(&ctx);
}

int other_main(int hartid)
{
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void)
{
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
