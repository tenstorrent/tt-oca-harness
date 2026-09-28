/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Secure DMA Basic Register Write Test
 *
 * This test verifies basic register read/write access to the Secure DMA
 * controller in the SEP subsystem. It writes test values to several
 * writable configuration registers and reads them back to verify.
 *
 * Secure DMA Base Address: 0x20000000 (SEP address space)
 */

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

// CFG_REGWEN values (multi-bit bool)
#define MUBI4_TRUE 0x6  // Unlocked
#define MUBI4_FALSE 0x9 // Locked

//==============================================================================
// Test Helper Functions
//==============================================================================

static int test_register_rw(const char *name, uint32_t addr, uint32_t test_val) {
    printf("  Testing %s @ 0x%08x\n", name, addr);

    // Write the test value
    WRITE_REG(addr, test_val);

    // Read it back
    uint32_t readback = READ_REG(addr);

    if (readback == test_val) {
        printf("    PASS: wrote 0x%08x, read 0x%08x\n", test_val, readback);
        return 0;
    } else {
        printf("    FAIL: wrote 0x%08x, read 0x%08x\n", test_val, readback);
        return -1;
    }
}

//==============================================================================
// Main Test
//==============================================================================

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    // Set up side effect region for DMA
    __asm__ volatile("csrw 0x7c0, %0" : : "r"(0x8));

    int errors = 0;

    printf("=== Secure DMA Basic Register Write Test ===\n\n");

    // Check that DMA is idle (CFG_REGWEN should be MUBI4_TRUE = 0x6)
    uint32_t cfg_regwen = READ_REG(SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    printf("CFG_REGWEN = 0x%x (expected 0x%x for unlocked)\n", cfg_regwen, MUBI4_TRUE);

    if ((cfg_regwen & 0xF) != MUBI4_TRUE) {
        printf("WARNING: DMA may be busy or locked\n");
    }

    //==========================================================================
    // Step 1: Configure the DMA enabled memory range (required before DMA use)
    //==========================================================================
    printf("\nConfiguring DMA enabled memory range:\n");

    // Set the allowed memory range for DMA operations
    WRITE_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    printf("  ENABLED_MEMORY_RANGE_BASE = 0x%08x\n",
           READ_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR));

    WRITE_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFF);
    printf("  ENABLED_MEMORY_RANGE_LIMIT = 0x%08x\n",
           READ_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR));

    // Mark the range as valid - this is required before DMA can operate
    WRITE_REG(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);
    printf("  RANGE_VALID = 0x%x\n", READ_REG(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR));

    //==========================================================================
    // Step 2: Test register writes
    //==========================================================================
    printf("\nTesting register writes:\n");

    // Test source address registers
    errors += test_register_rw("SRC_ADDR_LO", SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, 0x11000000);
    errors += test_register_rw("SRC_ADDR_HI", SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x00000000);

    // Test destination address registers
    errors += test_register_rw("DST_ADDR_LO", SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, 0x11001000);
    errors += test_register_rw("DST_ADDR_HI", SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x00000000);

    // Test size registers
    errors +=
        test_register_rw("TOTAL_DATA_SIZE", SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, 0x100);

    //============================================================================
    // Step 3: Test normal DMA operation - Simple Contiguous Transfer
    //============================================================================

    printf("\nTesting normal DMA operation (simple contiguous transfer):\n");
    printf("  Source: 0x%08lx, Destination: 0x%08lx, Size: 0x1000 bytes\n",
           SEP_TOP_SEP_SRAM_BASE_ADDR, SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000);

    // Initialize source memory with test pattern
    printf("  Initializing source memory with test pattern...\n");
    volatile uint32_t *src_ptr = (volatile uint32_t *)SEP_TOP_SEP_SRAM_BASE_ADDR;
    volatile uint32_t *dst_ptr = (volatile uint32_t *)(SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000);
    for (int i = 0; i < 0x1000 / 4; i++) {
        src_ptr[i] = 0xDEAD0000 + i; // Test pattern
        dst_ptr[i] = 0x00000000;     // Clear destination
    }

    // Set the source address
    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, SEP_TOP_SEP_SRAM_BASE_ADDR);
    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, SEP_TOP_SEP_SRAM_BASE_ADDR >> 32);

    // Set the destination address
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000);
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR,
              (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000) >> 32);

    // Configure address space IDs (both internal OT addresses)
    // SRC_ASID = 0x7 (bits [3:0]), DST_ASID = 0x7 (bits [7:4])
    WRITE_REG(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, 0x77);
    printf("  ADDR_SPACE_ID = 0x%x (SRC=OT_ADDR, DST=OT_ADDR)\n",
           READ_REG(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR));

    // Set the transfer width to 4 bytes (FOUR_BYTE = 0x2)
    WRITE_REG(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2);

    // Set the chunk data size (single chunk = total size)
    WRITE_REG(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, 0x1000);

    // Set the total data size
    WRITE_REG(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, 0x1000);

    // Configure source: INCREMENT=1 (bit 0), WRAP=0 (bit 1)
    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, 0x1);
    printf("  SRC_CONFIG = 0x%x (INCREMENT enabled)\n",
           READ_REG(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR));

    // Configure destination: INCREMENT=1 (bit 0), WRAP=0 (bit 1)
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, 0x1);
    printf("  DST_CONFIG = 0x%x (INCREMENT enabled)\n",
           READ_REG(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR));

    // Start the DMA transfer: OPCODE=COPY (0x0), INITIAL_TRANSFER=1 (bit 8), and GO=1 (bit 31)
    printf("  Starting DMA transfer...\n");
    WRITE_REG(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
              0x80000100); // GO bit set, INITIAL_TRANSFER bit set, OPCODE=COPY

    // Poll for completion
    printf("  Waiting for DMA completion...\n");
    uint32_t status;
    int timeout = 100000;
    while (timeout-- > 0) {
        status = READ_REG(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status & 0x2) { // DONE bit (bit 1)
            printf("  DMA transfer completed!\n");
            break;
        }
        if (status & 0x8) { // ERROR bit (bit 3)
            printf("  ERROR: DMA transfer failed!\n");
            uint32_t error_code = READ_REG(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
            printf("  ERROR_CODE = 0x%x\n", error_code);
            errors++;
            break;
        }
    }

    if (timeout <= 0) {
        printf("  ERROR: DMA transfer timeout!\n");
        errors++;
    }

    printf("  Final STATUS = 0x%x\n", status);

    // Verify the transfer
    printf("  Verifying transferred data...\n");
    int verify_errors = 0;
    for (int i = 0; i < 0x1000 / 4; i++) {
        if (dst_ptr[i] != src_ptr[i]) {
            printf("    Mismatch at offset 0x%x: expected 0x%08x, got 0x%08x\n", i * 4, src_ptr[i],
                   dst_ptr[i]);
            verify_errors++;
        }
    }

    if (verify_errors == 0) {
        printf("  PASS: All %d words transferred correctly!\n", 0x1000 / 4);
    } else {
        printf("  FAIL: %d/%d words had mismatches\n", verify_errors, 0x1000 / 4);
        errors += verify_errors;
    }

    printf("\n=== Test Summary ===\n");

    if (errors == 0) {
        printf("All register write tests PASSED\n");
        test_pass(0);
    } else {
        printf("FAILED: %d register(s) failed\n", errors);
        test_fail(errors);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
