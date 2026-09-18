/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Unsecure Boot Test - Transfer and Execute Bootcode
 *
 * This test transfers a bootcode binary from the master BFM to the DUT
 * and then executes it using the OCCP JUMP command.
 *
 * The test reads bootcode parameters from scratch registers (set by CocoTB),
 * transfers the bootcode in chunks, and then jumps to execute it.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>

// Maximum transfer size per OCCP write command
#define MAX_TRANSFER_CHUNK_SIZE 1024

static void run_unsecure_boot_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Unsecure Boot Test ===\n");

    ctx->overall_result = true;
    int retval;

    simputs("=== Reading bootcode parameters ===\n");

    // Read bootcode parameters from scratch registers (set by CocoTB)
    uint64_t master_bootcode_addr = read_scratch(5);
    uint64_t bootcode_size = read_scratch(6);
    uint64_t target_dut_addr = read_scratch(7);
    // Offset of main() within the bootcode image, published by the loader in scratch 8.
    uint64_t entry_offset = read_scratch(8);

    simputshex64("Master bootcode address: 0x", master_bootcode_addr);
    simputshex64("Bootcode size: 0x", bootcode_size);
    simputshex64("Target DUT address: 0x", target_dut_addr);
    simputshex64("Entry offset: 0x", entry_offset);

    simputs("=== Starting bootcode transfer to DUT ===\n");

    // Transfer bootcode in chunks
    uint64_t bytes_transferred = 0;
    uint64_t current_master_addr = master_bootcode_addr;
    uint64_t current_dut_addr = target_dut_addr;

    while (bytes_transferred < bootcode_size) {
        uint64_t remaining_bytes = bootcode_size - bytes_transferred;
        uint16_t chunk_size = (remaining_bytes > MAX_TRANSFER_CHUNK_SIZE)
                                  ? MAX_TRANSFER_CHUNK_SIZE
                                  : (uint16_t)remaining_bytes;

        // Read chunk from master BFM SRAM using local APIs
        uint8_t transfer_buffer[MAX_TRANSFER_CHUNK_SIZE];

        for (uint16_t i = 0; i < chunk_size; i++) {
            if ((i % 8) == 0 && (i + 8) <= chunk_size) {
                // Read 8 bytes at once for efficiency
                uint64_t *dest_ptr = (uint64_t *)&transfer_buffer[i];
                *dest_ptr = read_reg_64(current_master_addr + i);
                i += 7; // Skip next 7 bytes since we read 8
            } else {
                // Read single byte
                transfer_buffer[i] = read_reg(current_master_addr + i) & 0xFF;
            }
        }

        // Transfer chunk to DUT via OCCP
        retval = occp_send_write_command(ctx, ctx->slave_addr, current_dut_addr, transfer_buffer,
                                         chunk_size);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to transfer bootcode chunk\n");
            simputshex32("Transfer failed at offset 0x", (uint32_t)bytes_transferred);
            ctx->overall_result = false;
            return;
        }

        // Update addresses and counters
        current_master_addr += chunk_size;
        current_dut_addr += chunk_size;
        bytes_transferred += chunk_size;

        // Progress indicator
        if ((bytes_transferred % 1024) == 0) {
            simputshex32("Transferred 0x", (uint32_t)bytes_transferred);
            simputs(" bytes\n");
        }
    }

    simputs("=== Bootcode transfer completed successfully ===\n");
    simputshex64("Total bytes transferred: 0x", bytes_transferred);

    simputs("=== Executing OCCP JUMP command to start bootcode ===\n");

    // Execute jump command to start the bootcode
    retval = occp_send_jump_command(ctx, ctx->slave_addr, target_dut_addr + entry_offset);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: OCCP JUMP command failed\n");
        ctx->overall_result = false;
        return;
    }

    simputs("PASS: OCCP JUMP command executed successfully\n");
}

static void finalize_test_results(test_context_t *ctx) {
    if (ctx->overall_result) {
        simputs("OCCP UNSECURE BOOT TEST PASSED! Waiting for ROM to complete!\n");
        // Don't call test_pass here since we're waiting for ROM completion
        // The ROM will signal completion via its own test result
    } else {
        simputs("OCCP UNSECURE BOOT TEST FAILED!\n");
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

    // Set up test context
    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    // Run the test suite
    run_unsecure_boot_test(&test_ctx);

    // Finalize and report results
    finalize_test_results(&test_ctx);

    simputs("Done, waiting for ROM to complete\n");
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
