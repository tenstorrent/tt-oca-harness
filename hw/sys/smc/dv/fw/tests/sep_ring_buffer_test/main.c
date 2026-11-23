/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Ring Buffer Overflow/Underflow Test
 *
 * Verifies that the target ROM's SEP status ring buffer answers one successful GET_SEP_STATUS
 * for each entry it retains of those the testbench wrote, at most one less than its capacity,
 * and that further reads report an empty buffer. occp_send_get_sep_status_command compares each
 * entry, in FIFO order, with the shadow the testbench mirrors into controller SRAM. With the
 * STATUS_RPT_DISABLE strap set, every GET_SEP_STATUS must return Unsupported_StatusID instead,
 * and neither the entry values nor the empty buffer are checked. The testbench selects the
 * overflow or nominal case by the number of entries it writes. A GetVersion before the entries
 * are written and another after the drain show that no entry stops OCCP service.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

/* Value the testbench writes to scratch 10 once the entries are written */
#define COCOTB_READY_MAGIC 0xC0C07B00

#define SMC_RING_BUFFER_SIZE 512

/* Progress for the testbench in scratch 14; must match smc_sep_ring_buffer_driver.py. */
#define PHASE_SCRATCH 14
#define PHASE_BASELINE 0x5EB00001u
#define PHASE_DRAINED 0x5EB00002u
#define PHASE_LIVE 0x5EB00003u
#define PHASE_DONE 0x5EB00004u
/* The first two entries read back, in scratch 5 and 6. */
#define FIRST_ENTRY_SCRATCH 5
#define READBACK_SCRATCHES 2

#define OCCP_VERSION_1_0_0 0x1

static bool get_version_ok(test_context_t *ctx, const char *when) {
    uint32_t version = 0;
    int result = occp_send_get_version_command(ctx, ctx->slave_addr, &version);
    if (result != OCCP_SUCCESS || version != OCCP_VERSION_1_0_0) {
        simputs("FAIL: GET_VERSION ");
        simputs(when);
        simputshex32(" returned version 0x", version);
        return false;
    }
    simputs("GET_VERSION ");
    simputs(when);
    simputs(" passed\n");
    return true;
}

/* Wait for the testbench to signal that the entries are written. */
static bool wait_for_cocotb_ready(void) {
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

/* Read the number of entries the testbench wrote. */
static uint32_t get_entry_count(void) {
    simputs("\n=== Reading Entry Count ===\n");
    uint32_t count = read_scratch(12);

    simputs("Entry count read from Scratch 12\n");
    simputshex32("  Number of entries: ", count);
    return count;
}

static bool read_and_validate_sep_status_buffer(test_context_t *ctx) {
    uint32_t total_written = get_entry_count();
    simputshex32("Total entries written: ", total_written);

    simputs("\n=== Reading Buffer Contents ===\n");
    /* The ring keeps one slot empty, so it retains at most SMC_RING_BUFFER_SIZE - 1 entries */
    for (uint32_t i = 0;
         i <
         (total_written > (SMC_RING_BUFFER_SIZE - 1) ? (SMC_RING_BUFFER_SIZE - 1) : total_written);
         i++) {
        uint32_t status = 0;

        int result = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status);

        if (result != OCCP_SUCCESS) {
            simputs("FAIL: GET_SEP_STATUS failed\n");
            simputshex32("  Entry index: ", i);
            ctx->overall_result = false;
            return false;
        } else if (ctx->status_reporting_disabled) {
            simputs("GET_SEP_STATUS rejected as expected under STATUS_RPT_DISABLE\n");
            simputshex32("  Entry index: ", i);
        } else {
            simputs("GET_SEP_STATUS command passed\n");
            simputshex32("  Entry index: ", i);
            simputshex32("  Status:      0x", status);
            if (i < READBACK_SCRATCHES) {
                write_scratch(FIRST_ENTRY_SCRATCH + i, status);
            }
        }
    }
    write_scratch(PHASE_SCRATCH, PHASE_DRAINED);

    if (!get_version_ok(ctx, "after the drain")) {
        ctx->overall_result = false;
        return false;
    }
    write_scratch(PHASE_SCRATCH, PHASE_LIVE);

    simputs("\n=== Verifying Buffer Empty ===\n");
    uint32_t status_after = 0;
    /* Every read past the last retained entry must report an empty buffer */
    for (int i = 0; i < 10; i++) {
        int result = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status_after);

        if (result == OCCP_SUCCESS && ctx->status_reporting_disabled) {
            simputs("GET_SEP_STATUS rejected as expected under STATUS_RPT_DISABLE\n");
        } else if (result == OCCP_SUCCESS && status_after == 0) {
            simputs("PASS: Buffer empty after reading all entries\n");
        } else {
            simputs("FAIL: Buffer not empty\n");
            simputshex32("  Unexpected status: 0x", status_after);
            ctx->overall_result = false;
            return false;
        }
    }
    write_scratch(PHASE_SCRATCH, PHASE_DONE);

    return true;
}

/* Report the overall result via scratch registers. */
static void finalize_test_results(test_context_t *ctx) {
    simputs("\n========================================\n");
    simputs("FINAL TEST RESULTS\n");
    simputs("========================================\n");

    if (ctx->overall_result) {
        simputs("\n*** ALL TESTS PASSED ***\n");
        test_pass(0);
    } else {
        simputs("\n*** TESTS FAILED ***\n");
        test_fail(0);
    }
}

int main(void) {
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

    /* The testbench writes no entry until this baseline is published. */
    if (!get_version_ok(&ctx, "before the entries")) {
        test_fail(0);
    }
    write_scratch(PHASE_SCRATCH, PHASE_BASELINE);

    if (!wait_for_cocotb_ready()) {
        simputs("FAIL: Cocotb ready timeout\n");
        test_fail(0);
    }

    read_and_validate_sep_status_buffer(&ctx);
    finalize_test_results(&ctx);
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
