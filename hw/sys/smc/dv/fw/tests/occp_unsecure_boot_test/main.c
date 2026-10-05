/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Loads a bootcode image from controller memory into the target with OCCP WRITE, then JUMPs to
 * its entry point. The harness supplies the image layout; the booted image reports the verdict.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

#define MAX_TRANSFER_CHUNK_SIZE 1024

static void run_unsecure_boot_test(test_context_t *ctx) {
    simputs("=== Starting OCCP Unsecure Boot Test ===\n");

    ctx->overall_result = true;
    int retval;

    simputs("=== Reading bootcode parameters ===\n");

    uint64_t master_bootcode_addr = read_scratch(5);
    uint64_t bootcode_size = read_scratch(6);
    uint64_t target_dut_addr = read_scratch(7);
    uint64_t entry_offset = read_scratch(8);

    simputshex64("Master bootcode address: 0x", master_bootcode_addr);
    simputshex64("Bootcode size: 0x", bootcode_size);
    simputshex64("Target DUT address: 0x", target_dut_addr);
    simputshex64("Entry offset: 0x", entry_offset);

    simputs("=== Starting bootcode transfer to DUT ===\n");

    uint64_t bytes_transferred = 0;
    uint64_t current_master_addr = master_bootcode_addr;
    uint64_t current_dut_addr = target_dut_addr;

    while (bytes_transferred < bootcode_size) {
        uint64_t remaining_bytes = bootcode_size - bytes_transferred;
        uint16_t chunk_size = (remaining_bytes > MAX_TRANSFER_CHUNK_SIZE)
                                  ? MAX_TRANSFER_CHUNK_SIZE
                                  : (uint16_t)remaining_bytes;

        uint8_t transfer_buffer[MAX_TRANSFER_CHUNK_SIZE];

        for (uint16_t i = 0; i < chunk_size; i++) {
            if ((i % 8) == 0 && (i + 8) <= chunk_size) {
                uint64_t *dest_ptr = (uint64_t *)&transfer_buffer[i];
                *dest_ptr = read_reg_64(current_master_addr + i);
                i += 7;
            } else {
                transfer_buffer[i] = read_reg(current_master_addr + i) & 0xFF;
            }
        }

        retval = occp_send_write_command(ctx, ctx->slave_addr, current_dut_addr, transfer_buffer,
                                         chunk_size);
        if (retval != OCCP_SUCCESS) {
            simputs("FAIL: Failed to transfer bootcode chunk\n");
            simputshex32("Transfer failed at offset 0x", (uint32_t)bytes_transferred);
            ctx->overall_result = false;
            return;
        }

        current_master_addr += chunk_size;
        current_dut_addr += chunk_size;
        bytes_transferred += chunk_size;

        if ((bytes_transferred % 1024) == 0) {
            simputshex32("Transferred 0x", (uint32_t)bytes_transferred);
            simputs(" bytes\n");
        }
    }

    simputs("=== Bootcode transfer completed successfully ===\n");
    simputshex64("Total bytes transferred: 0x", bytes_transferred);

    simputs("=== Executing OCCP JUMP command to start bootcode ===\n");

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
        // No test_pass() here: the DUT side reports the verdict after the boot.
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

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

    run_unsecure_boot_test(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done, waiting for ROM to complete\n");
    while (1) {
        __asm__("wfi");
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
