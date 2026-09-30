/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Transfers a bootcode image from the master BFM to the DUT with OCCP WRITE, then sends
 * VALIDATE_BOOT at its entry point. Image parameters come from scratch registers 4-7, set by
 * the harness.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>

#define MAX_TRANSFER_CHUNK_SIZE 248

static void run_secure_boot_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Secure Boot Test ===\n");

    ctx->overall_result = true;
    int retval;

    simputs("=== Random OCCP Commands (5 commands) ===\n");
    execute_random_commands(ctx, 5);

    simputs("=== Reading bootcode parameters ===\n");

    uint64_t entry_offset = read_scratch(4);
    uint64_t master_bootcode_addr = read_scratch(5);
    uint64_t bootcode_size = read_scratch(6);
    uint64_t target_dut_addr = read_scratch(7);

    simputshex64("Entry offset: 0x", entry_offset);
    simputshex64("Master bootcode address: 0x", master_bootcode_addr);
    simputshex64("Bootcode size: 0x", bootcode_size);
    simputshex64("Target DUT address: 0x", target_dut_addr);

    simputs("=== Starting bootcode transfer to DUT ===\n");

    uint64_t bytes_transferred = 0;
    uint64_t current_master_addr = master_bootcode_addr;
    uint64_t current_dut_addr = target_dut_addr;

    while (bytes_transferred < bootcode_size) {
        uint64_t chunk_size = bootcode_size - bytes_transferred;
        if (chunk_size > MAX_TRANSFER_CHUNK_SIZE) {
            chunk_size = MAX_TRANSFER_CHUNK_SIZE;
        }

        simputshex64("Transferring chunk from master addr: 0x", current_master_addr);
        simputshex64(" to DUT addr: 0x", current_dut_addr);
        simputshex64(" size: 0x", chunk_size);

        retval = occp_send_write_command(ctx, ctx->slave_addr, current_dut_addr,
                                         current_master_addr, chunk_size);

        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: OCCP WRITE command failed during bootcode transfer\n");
            ctx->overall_result = false;
            return;
        }

        bytes_transferred += chunk_size;
        current_master_addr += chunk_size;
        current_dut_addr += chunk_size;

        simputshex64("Bytes transferred so far: 0x", bytes_transferred);
    }

    simputs("PASS: Bootcode transfer completed successfully\n");

    simputs("=== Executing OCCP VALIDATE_BOOT command ===\n");

    // The harness uses this address as the cores' reset vector, so it must be the entry point.
    uint64_t manifest_addr = target_dut_addr + entry_offset;
    retval = occp_send_validate_boot_command(ctx, ctx->slave_addr, manifest_addr);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: OCCP VALIDATE_BOOT command failed\n");
        ctx->overall_result = false;
        return;
    }

    simputs("PASS: OCCP VALIDATE_BOOT command executed successfully\n");
    simputshex64("Manifest address sent: 0x", manifest_addr);
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("OCCP SECURE BOOT TEST PASSED! Waiting for ROM to complete validation!\n");
        // No test_pass() here: the DUT side reports the verdict after the boot.
    } else {
        simputs("OCCP SECURE BOOT TEST FAILED!\n");
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
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_secure_boot_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done, waiting for ROM to complete validation and boot\n");
    while (1) {
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
