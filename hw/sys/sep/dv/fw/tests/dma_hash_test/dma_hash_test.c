/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Secure DMA SHA-256 Hash Test
 *
 * This test transfers data from SRAM to DCCM and uses the hash engine in the
 * DMA to compute the SHA-256 hash of the data. It then verifies the hash against
 * the expected hash, calculated by software SHA256 library.
 *
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sha256.h"
#include "sep_pic.h"

// Interrupt source IDs (from hw/sys/sep/rtl/sep.sv). PIC source = internal index + 1
// (VeeR EL2 PIC source 0 is the tied no-interrupt source). After the 8-slot
// mailbox reallocation, the DMA interrupts moved up by 8:
//   intr_dma_done       -> sep_internal_interrupts[8]  -> PIC source 9
//   intr_dma_chunk_done -> sep_internal_interrupts[10] -> PIC source 11
//   intr_dma_error      -> sep_internal_interrupts[11] -> PIC source 12
#define EXT_INT_DMA_DONE 9
#define EXT_INT_DMA_CHUNK_DONE 11
#define EXT_INT_DMA_ERROR 12

// Flag set by interrupt handler
static volatile uint32_t dma_interrupt_fired = 0;

// DMA interrupt handler - clears interrupt at source
void __attribute__((interrupt("machine"))) dma_isr(void) {
    dma_interrupt_fired = 1;
    volatile uint32_t *status = (volatile uint32_t *)OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR;
    *status = SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm |
              SECURE_DMA__STATUS__CHUNK_DONE_bm;
    __asm__ volatile("fence" ::: "memory");
}

// CFG_REGWEN values (multi-bit bool)
#define MUBI4_TRUE 0x6  // Unlocked
#define MUBI4_FALSE 0x9 // Locked

// ASID values (from RDL enum asid_e)
#define ASID_OT_ADDR 0x7  // OpenTitan 32-bit internal bus
#define ASID_SYS_ADDR 0x9 // SoC system address bus
#define ASID_SOC_ADDR 0xa // SoC control register bus

// Opcode values (from RDL enum opcode_e)
#define OPCODE_COPY 0x0
#define OPCODE_SHA256 0x1
#define OPCODE_SHA384 0x2
#define OPCODE_SHA512 0x3

// Transfer width values (from RDL enum transfer_width_e)
#define TRANSFER_WIDTH_ONE_BYTE 0x0
#define TRANSFER_WIDTH_TWO_BYTE 0x1
#define TRANSFER_WIDTH_FOUR_BYTE 0x2

// Test data size in bytes - must be a multiple of 4
// 64 bytes = 1 SHA block + padding = ~8-10K cycles for SW hash
// 128 bytes = 2 SHA blocks + padding = ~12-15K cycles
// 4096 (0x1000) bytes = 64 blocks = ~300-400K cycles
#ifndef TEST_DATA_SIZE
#define TEST_DATA_SIZE 0x100
#endif

//==============================================================================
// Hashing Functions
//==============================================================================

// Function to compute the SHA256 hash
void compute_sha256(const unsigned char *data, size_t data_len, unsigned char *hash_output) {
    SHA256_CTX ctx;

    // Initialize the SHA256 context
    sha256_init(&ctx);

    // Feed the data into the hash function
    sha256_update(&ctx, data, data_len);

    // Finalize and retrieve the hash
    sha256_final(&ctx, hash_output);
}

//==============================================================================
// Main Test
//==============================================================================

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    // Set up DMA interrupts
    pic_register_handler(EXT_INT_DMA_DONE, dma_isr);
    pic_register_handler(EXT_INT_DMA_ERROR, dma_isr);
    pic_set_gateway(EXT_INT_DMA_DONE, 0, 0); // level-triggered, active-high
    pic_set_gateway(EXT_INT_DMA_ERROR, 0, 0);
    pic_set_priority(EXT_INT_DMA_DONE, 1);
    pic_set_priority(EXT_INT_DMA_ERROR, 1);
    pic_enable_source(EXT_INT_DMA_DONE);
    pic_enable_source(EXT_INT_DMA_ERROR);
    pic_enable_interrupts();
    printf("STEP filter init done; DMA done/error handlers registered\n");

    int errors = 0;

    printf("=== Secure DMA SHA-256 Hash Test ===\n\n");

    // Check that DMA is idle (CFG_REGWEN should be MUBI4_TRUE = 0x6)
    uint32_t cfg_regwen = READ_REG(OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    printf("CFG_REGWEN = 0x%x (expected 0x%x for unlocked)\n", cfg_regwen, MUBI4_TRUE);

    if ((cfg_regwen & 0xF) != MUBI4_TRUE) {
        // Must count as an error, not warn and continue. This is the only check
        // that the config write-enable is actually open before we program the
        // DMA; if it merely warned, a CFG_REGWEN stuck locked or reading as an
        // unmapped 0x0 would print a line nobody reads and the test would still
        // pass while claiming the lock was verified open.
        printf("ERROR: CFG_REGWEN not unlocked (DMA busy or locked)\n");
        errors++;
    }

    //==========================================================================
    // Step 1: Configure the DMA enabled memory range (required before DMA use)
    //==========================================================================
    printf("\nConfiguring DMA enabled memory range:\n");

    // Set the allowed memory range for DMA operations
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    printf("  ENABLED_MEMORY_RANGE_BASE = 0x%08x\n",
           READ_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR));

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFF);
    printf("  ENABLED_MEMORY_RANGE_LIMIT = 0x%08x\n",
           READ_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR));

    // Mark the range as valid - this is required before DMA can operate
    secure_dma__RANGE_VALID_t range_valid = {.f = {.RANGE_VALID = 1}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, range_valid.w);
    printf("  RANGE_VALID = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR));

    //==========================================================================
    // Step 2: Write random data to SRAM
    //==========================================================================

    // Generate random data directly in SRAM (avoid stack overflow)
    printf("  Generating random data in SRAM...\n");
    volatile uint32_t *src_ptr = (volatile uint32_t *)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR;
    for (int i = 0; i < TEST_DATA_SIZE / 4; i++) {
        src_ptr[i] = (uint32_t)rand();
    }

    //==========================================================================
    // Step 2: Configure the DMA transfer from SRAM to DCCM
    //==========================================================================
    printf("\nConfiguring DMA transfer from SRAM to DCCM:\n");

    // Set the source address
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, OCH_SEP_TOP_SEP_SRAM_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, OCH_SEP_TOP_SEP_SRAM_BASE_ADDR >> 32);

    // Set the destination address (use high DCCM to avoid BSS overlap)
    // BSS is at low DCCM (~0x80000-0x80FFF), so use 0x82000+
#define DMA_DST_ADDR (OCH_SEP_TOP_SEP_DCCM_BASE_ADDR + 0x2000)
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, DMA_DST_ADDR);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, DMA_DST_ADDR >> 32);

    // Configure address space IDs (both internal OT addresses)
    secure_dma__ADDR_SPACE_ID_t addr_space_id = {
        .f = {.SRC_ASID = ASID_OT_ADDR, .DST_ASID = ASID_OT_ADDR}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, addr_space_id.w);
    printf("  ADDR_SPACE_ID = 0x%x (SRC=OT_ADDR, DST=OT_ADDR)\n",
           READ_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR));

    // Set the transfer width to 4 bytes
    secure_dma__TRANSFER_WIDTH_t transfer_width = {.f = {.WIDTH = TRANSFER_WIDTH_FOUR_BYTE}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, transfer_width.w);

    // Set the chunk data size (single chunk = total size)
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, TEST_DATA_SIZE);

    // Set the total data size
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, TEST_DATA_SIZE);

    // Configure source: increment address after each transfer
    secure_dma__SRC_CONFIG_t src_config = {.f = {.INCREMENT = 1, .WRAP = 0}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, src_config.w);
    printf("  SRC_CONFIG = 0x%x (INCREMENT enabled)\n",
           READ_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR));

    // Configure destination: increment address after each transfer
    secure_dma__DST_CONFIG_t dst_config = {.f = {.INCREMENT = 1, .WRAP = 0}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, dst_config.w);
    printf("  DST_CONFIG = 0x%x (INCREMENT enabled)\n",
           READ_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR));

    // Dump all configuration registers before starting transfer
    printf("\nDMA Configuration before GO:\n");
    printf("  SRC_ADDR    = 0x%08x%08x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR),
           READ_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR));
    printf("  DST_ADDR    = 0x%08x%08x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR),
           READ_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR));
    printf("  TOTAL_SIZE  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR));
    printf("  CHUNK_SIZE  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR));
    printf("  XFER_WIDTH  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR));
    printf("  ADDR_SPACE  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR));
    printf("  SRC_CONFIG  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR));
    printf("  DST_CONFIG  = 0x%x\n", READ_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR));

    // Enable DMA interrupts in the DMA controller
    secure_dma__INTR_ENABLE_t intr_enable = {
        .f = {.DMA_DONE = 1, .DMA_CHUNK_DONE = 0, .DMA_ERROR = 1}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR, intr_enable.w);

    // Start the DMA transfer: OPCODE=SHA256 (0x1), INITIAL_TRANSFER=1 (bit 8), and GO=1 (bit 31)
    // IMPORTANT: Printf before starting DMA to avoid DCCM contention (format strings are in DCCM)
    printf("\nStarting DMA transfer...\n");
    printf("  Waiting for DMA completion (WFI-based)...\n");

    // Configure and start DMA transfer with SHA-256 hashing
    // DIGEST_SWAP converts digest to big-endian to match SW SHA-256 output
    secure_dma__CONTROL_t control = {
        .f = {.OPCODE = OPCODE_SHA256, .DIGEST_SWAP = 1, .INITIAL_TRANSFER = 1, .GO = 1}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, control.w);

    // Wait for DMA completion using WFI
    // The interrupt handler sets dma_interrupt_fired flag and clears STATUS.DONE
    // So we check the flag instead of STATUS register
    int timeout = 100000;
    while (timeout-- > 0) {
        __asm__ volatile("wfi"); // Sleep until interrupt pending

        // Check flag set by interrupt handler
        if (dma_interrupt_fired) break;
    }

    // Check ERROR_CODE to see if there was an error
    // (STATUS bits are cleared by the interrupt handler)
    secure_dma__ERROR_CODE_t error_code;
    error_code.w = READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);

    // Process result
    if (dma_interrupt_fired && error_code.w == 0) { // Success
        printf("  DMA transfer completed!\n");
    } else if (error_code.w != 0) { // Error occurred
        printf("  ERROR: DMA transfer failed!\n");
        printf("  ERROR_CODE = 0x%x\n", error_code.w);

        // Decode error bits using struct fields
        if (error_code.f.SRC_ADDR_ERROR)
            printf("    - SRC_ADDR_ERROR: Source address is invalid\n");
        if (error_code.f.DST_ADDR_ERROR)
            printf("    - DST_ADDR_ERROR: Destination address is invalid\n");
        if (error_code.f.OPCODE_ERROR) printf("    - OPCODE_ERROR: Opcode is invalid\n");
        if (error_code.f.SIZE_ERROR) printf("    - SIZE_ERROR: Size/width configuration invalid\n");
        if (error_code.f.BUS_ERROR) printf("    - BUS_ERROR: Bus transfer returned an error\n");
        if (error_code.f.BASE_LIMIT_ERROR)
            printf("    - BASE_LIMIT_ERROR: Base/limit addresses invalid\n");
        if (error_code.f.RANGE_VALID_ERROR)
            printf("    - RANGE_VALID_ERROR: Memory range not configured\n");
        if (error_code.f.ASID_ERROR)
            printf("    - ASID_ERROR: Source or destination ASID invalid\n");

        errors++;
    } else {
        printf("  ERROR: DMA transfer timeout!\n");
        // Abort DMA
        secure_dma__CONTROL_t abort_ctrl = {.f = {.ABORT = 1}};
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, abort_ctrl.w);
        errors++;
    }

    //============================================================================
    // Step 3: Compute the SHA-256 hash using software library
    //============================================================================

    printf("\nComputing SHA-256 hash using software library...\n");

    // Compute the SHA-256 hash using software library
    uint8_t sw_hash[32];
    compute_sha256((unsigned char *)src_ptr, TEST_DATA_SIZE, sw_hash);

    //==========================================================================
    // Step 4: Verify the hash against the expected hash
    //==========================================================================
    printf("\nVerifying SHA-256 hash against expected hash...\n");

    uint32_t expected_hash[8];
    for (int i = 0; i < 8; i++) {
        expected_hash[i] = READ_REG(OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR + i * 4);
    }

    // Cast the 32-bit array to an 8-bit pointer for memcmp
    uint8_t *hw_hash = (uint8_t *)expected_hash;

    // Print neatly as a continuous hex string
    printf("  Expected (HW) = 0x");
    for (int i = 0; i < 32; i++) {
        printf("%02x", hw_hash[i]);
    }
    printf("\n");

    printf("  Computed (SW) = 0x");
    for (int i = 0; i < 32; i++) {
        printf("%02x", sw_hash[i]);
    }
    printf("\n");

    // Safe to use memcmp now! Both are treated as 32-byte streams.
    if (memcmp(hw_hash, sw_hash, 32) != 0) {
        printf("  ERROR: SHA-256 hash mismatch!\n");
        errors++;
    }

    //==========================================================================
    // Step 5: Verify data in SRAM and DCCM matches
    //==========================================================================
    printf("\nVerifying data in SRAM and DCCM matches...\n");

    // Get pointer to DCCM for comparison (must match DMA_DST_ADDR)
    volatile uint32_t *dccm_ptr = (volatile uint32_t *)DMA_DST_ADDR;

    int copy_mismatches = 0;
    for (int i = 0; i < TEST_DATA_SIZE / 4; i++) {
        if (src_ptr[i] != dccm_ptr[i]) {
            printf("  ERROR: Data mismatch at offset 0x%x: SRAM=0x%08x, DCCM=0x%08x\n", i * 4,
                   src_ptr[i], dccm_ptr[i]);
            errors++;
            copy_mismatches++;
        }
    }

    // Gate the pass token on the compare it claims to report. Printed
    // unconditionally it appeared in failing runs too, so a log containing it
    // was not evidence that the copy matched.
    if (copy_mismatches == 0) {
        printf("  PASS: SRAM and DCCM data matches!\n");
    }

    printf("\n=== Test Summary ===\n");

    if (errors == 0) {
        printf("All SHA-256 hash tests PASSED\n");
        test_pass(0);
    } else {
        printf("FAILED: %d SHA-256 hash test(s) failed\n", errors);
        test_fail(errors);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
