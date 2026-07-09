/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stdio.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_dma.h"
#include "smc_test.h"
#include "virt_console.h"

// Set to 1 if you want debug messages & to be able to check data in the sram when viewing the
// waveform (also compile with USE_VERILOG_MEM_ARRAY flag)
#define DEBUG 0

#if DEBUG
_Atomic int src_data_written = 0;
_Atomic int src_data_read = 0;
#endif

// Note: stride is the distance in bytes between the start of one block and the next
// MAKE SURE STRIDE IS GREATER THAN OR EQUAL TO BLOCK SIZE otherwise you get overlap
const uint64_t src_addr = 0xC0080000;
const uint64_t src_stride = 0x200;
const uint64_t dst_addr = src_addr + 0x10000;
const uint64_t dst_stride = 0x400;
const uint64_t ret_addr = dst_addr + 0x10000;
const uint64_t ret_stride = 0x800;
const uint64_t block_size = 0x100;
const uint64_t num_blocks = 0x2;

int main(void) {

    // Write to src_addr for block_size * num_blocks
    init_test(0);
    simputs("Initializing source data...\n");
    volatile uint64_t *src = (uint64_t *)(src_addr);
    for (uint64_t block = 0; block < num_blocks; block++) {
        for (uint64_t i = 0; i < block_size / sizeof(uint64_t); i++) {
            src[(block * (src_stride / sizeof(uint64_t))) + i] =
                get_random_int() << 32 | get_random_int();
        }
    }
#if DEBUG
    metal_atomic_swap(&src_data_written, 1);

    int is_ready = 1;
    do {
        is_ready = metal_atomic_add(&src_data_read, 0);
    } while (!is_ready);
#endif

    simputs("Source data initialized\n");

    // Initialize the DMA
    smc_dma_init();
    simputs("DMA initialized\n");

    // First DMA transfer: from FRONT to SYSTEM_OUT
    dma_cmd_t cmd1 = {
        .src_addr = src_addr,
        .src_stride = src_stride,
        .dst_addr = dst_addr,
        .dst_stride = dst_stride,
        .length = block_size,
        .num_blocks = num_blocks,
        .id = 0x0,
    };
    smc_dma_issue_cmd(&cmd1);
    smc_dma_wait_cmd_done(&cmd1);
    simputs("First DMA transfer completed\n");

    // Second DMA transfer: from SYSTEM_OUT back to FRONT
    dma_cmd_t cmd2 = {
        .src_addr = dst_addr,
        .src_stride = dst_stride,
        .dst_addr = ret_addr,
        .dst_stride = ret_stride,
        .length = block_size,
        .num_blocks = num_blocks,
        .id = 0x0,
    };
    smc_dma_issue_cmd(&cmd2);
    smc_dma_wait_cmd_done(&cmd2);
    simputs("Second DMA transfer completed\n");

    // Check that the data is the same, using 64-bit comparison
    volatile uint64_t *addr1 = (uint64_t *)(src_addr);
    volatile uint64_t *addr2 = (uint64_t *)(ret_addr);
    bool is_equal = true;
    char debug_msg[100];
    for (int block = 0; block < num_blocks; block++) {
        for (int i = 0; i < block_size / sizeof(uint64_t); i++) {
#if DEBUG
            snprintf(debug_msg, sizeof(debug_msg), "Addr1 (0x%lX): 0x%lX, Addr2 (0x%lX): 0x%lX\n",
                     src_addr + (block * (src_stride / sizeof(uint64_t))) + i,
                     addr1[(block * (src_stride / sizeof(uint64_t))) + i],
                     ret_addr + (block * (ret_stride / sizeof(uint64_t))) + i,
                     addr2[(block * (ret_stride / sizeof(uint64_t))) + i]);
            simputs(debug_msg);
#endif
            // Compare the data
            if (addr1[(block * (src_stride / sizeof(uint64_t))) + i] !=
                addr2[(block * (ret_stride / sizeof(uint64_t))) + i]) {
                is_equal = false;
                break;
            }
        }
        if (!is_equal) break;
    }
    simputs(is_equal ? "Data matches after DMA transfer\n" : "Data mismatch after DMA transfer\n");

    // Test result
    if (!is_equal) {
        test_fail(0);
    } else {
        test_pass(0);
    }

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {

#if DEBUG
    int is_ready = 0;
    do {
        is_ready = metal_atomic_add(&src_data_written, 0);
    } while (!is_ready);

    // Read entire src_addr to ensure data is in sram from dcache
    volatile uint64_t *src = (uint64_t *)(src_addr);
    for (uint64_t block = 0; block < num_blocks; block++) {
        for (uint64_t i = 0; i < block_size / sizeof(uint64_t); i++) {
            volatile data = src[(block * (src_stride / sizeof(uint64_t))) + i];
            (void)data;
        }
    }

    metal_atomic_swap(&src_data_read, 1);
#endif

    while (true) {
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
