/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Secure DMA inline hash test: SHA-256 and SHA-384.
 *
 * Two passes over the same SRAM-to-DCCM path, both with the DMA's inline hash
 * engine enabled.
 *
 * Pass 1, SHA-256: transfers build-varying data and checks the hardware digest
 * against a software SHA-256 computed over the same bytes, plus a byte compare
 * of the copy.
 *
 * Pass 2, SHA-384: there is no 64-bit SHA-2 core in this firmware, so the
 * expectation is the published FIPS 180-4 digest for a fixed 56-byte message
 * rather than a software hash. The message is the input and the vector is the
 * expectation; neither is read back from the engine. The copy is checked too,
 * so a correct digest over a broken copy still fails.
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_dma.h"
#include "sep_outbound_filter.h"
#include "sha256.h"
#include "sep_pic.h"

// PIC source = sep_internal_interrupts index + 1 (done [8]->9, error [11]->12).
#define EXT_INT_DMA_DONE 9
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
// CFG_REGWEN unlocked. SEP_DMA_REGWEN_UNLOCKED (fw/drivers/sep_dma.h) is
// SECURE_DMA__CFG_REGWEN__REGWEN_reset from the generated header, so this
// tracks an RDL change instead of rotting as a copied literal.
#define MUBI4_TRUE SEP_DMA_REGWEN_UNLOCKED

// ASID / opcode / width used by this SHA-256 copy.
#define ASID_OT_ADDR 0x7
#define OPCODE_SHA256 0x1
// SHA-384 opcode from the DV-owned encoding table (fw/drivers/sep_dma.h).
#define OPCODE_SHA384 SEP_DMA_OPCODE_SHA384
#define TRANSFER_WIDTH_FOUR_BYTE 0x2

// SHA-384 digest is 384 bits = 12 of the 16 SHA2_DIGEST words.
#define SHA384_DIGEST_WORDS 12
#define SHA384_DIGEST_BYTES 48

// FIPS 180-4 second SHA-2 test message, 56 bytes. Chosen over the one-block
// "abc" vector because the DMA transfers whole 4-byte words, and 56 is a
// multiple of 4 where 3 is not. The digest below is the published constant for
// this exact message, not a value read back from the engine.
static const char kFips1804Msg[] = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
#define FIPS_MSG_LEN 56
static const char kFips1804Sha384Hex[] =
    "3391fdddfc8dc7393707a65b1b4709397cf8b1d162af05abfe8f450de5f36bc6"
    "b0455a8520bc4e6f5fe95b1fe3c8452b";
// FIPS 180-4 SHA-256 of the same 56-byte message, for the multi-chunk pass.
static const char kFips1804Sha256Hex[] =
    "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1";
#define SHA256_DIGEST_WORDS 8
#define SHA256_DIGEST_BYTES 32
// 56 bytes as two 28-byte chunks. Both are word multiples, which the 4-byte
// transfer width requires, and 28 != 56 is what makes the transfer multi-chunk.
#define FIPS_CHUNK_LEN 28

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

// Render a big-endian digest byte stream as lowercase hex, for comparison
// against a published vector string.
static void digest_to_hex(const uint8_t *digest, size_t n, char *out) {
    static const char hex_chars[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        out[2 * i] = hex_chars[(digest[i] >> 4) & 0xF];
        out[2 * i + 1] = hex_chars[digest[i] & 0xF];
    }
    out[2 * n] = '\0';
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
        // This is the only check that the config write-enable is open before the
        // DMA is programmed: a CFG_REGWEN stuck locked, or reading as an unmapped
        // 0x0, fails the test here.
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
    secure_dma__TRANSFER_WIDTH_t transfer_width = {
        .f = {.TRANSACTION_WIDTH = TRANSFER_WIDTH_FOUR_BYTE}};
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
        expected_hash[i] = READ_REG(OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR(i));
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

    // Gate the pass token on the compare it claims to report.
    if (copy_mismatches == 0) {
        printf("  PASS: SRAM and DCCM data matches!\n");
    }

    //==========================================================================
    // Step 6: Second pass -- inline SHA-384 over the FIPS 180-4 test message
    //==========================================================================
    // The SHA-256 pass above hashes seed-varying data and checks it against a
    // software SHA-256 computed over the same bytes. There is no 64-bit SHA-2
    // core in this firmware, so SHA-384 is instead pinned to the published FIPS
    // 180-4 digest for a fixed message. The message is the input, the vector is
    // the expectation, and neither comes from the DMA.
    printf("\n=== Secure DMA SHA-384 (FIPS 180-4 vector) ===\n");

    // Stage the fixed message in SRAM, where the SHA-256 pass left random data.
    volatile uint8_t *msg_ptr = (volatile uint8_t *)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR;
    for (int i = 0; i < FIPS_MSG_LEN; i++) {
        msg_ptr[i] = (uint8_t)kFips1804Msg[i];
    }
    __asm__ volatile("fence" ::: "memory");

    // Same src/dst/width/ASID as the first pass; only the length and the opcode
    // change.
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, FIPS_MSG_LEN);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, FIPS_MSG_LEN);

    dma_interrupt_fired = 0;
    __asm__ volatile("fence" ::: "memory");

    secure_dma__CONTROL_t sha384_ctrl = {
        .f = {.OPCODE = OPCODE_SHA384, .DIGEST_SWAP = 1, .INITIAL_TRANSFER = 1, .GO = 1}};
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, sha384_ctrl.w);

    int sha384_timeout = 100000;
    while (sha384_timeout-- > 0) {
        __asm__ volatile("wfi");
        if (dma_interrupt_fired) break;
    }

    secure_dma__ERROR_CODE_t sha384_err;
    sha384_err.w = READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);

    if (!dma_interrupt_fired) {
        printf("  ERROR: SHA-384 DMA transfer timeout!\n");
        secure_dma__CONTROL_t abort_ctrl = {.f = {.ABORT = 1}};
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, abort_ctrl.w);
        errors++;
    } else if (sha384_err.w != 0) {
        // OPCODE_ERROR here would mean the engine does not accept OpcSha384 on
        // this build, which is a real result and not something to skip past.
        printf("  ERROR: SHA-384 DMA transfer failed, ERROR_CODE = 0x%x\n", sha384_err.w);
        if (sha384_err.f.OPCODE_ERROR) printf("    - OPCODE_ERROR: SHA-384 opcode rejected\n");
        errors++;
    } else {
        printf("  SHA-384 DMA transfer completed!\n");

        uint32_t hw384[SHA384_DIGEST_WORDS];
        for (int i = 0; i < SHA384_DIGEST_WORDS; i++) {
            hw384[i] = READ_REG(OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR(i));
        }

        char got_hex[2 * SHA384_DIGEST_BYTES + 1];
        digest_to_hex((const uint8_t *)hw384, SHA384_DIGEST_BYTES, got_hex);

        printf("  Computed (HW) = %s\n", got_hex);
        printf("  Expected (NIST) = %s\n", kFips1804Sha384Hex);

        if (strcmp(got_hex, kFips1804Sha384Hex) != 0) {
            printf("  ERROR: SHA-384 digest does not match the FIPS 180-4 vector!\n");
            errors++;
        } else {
            printf("  PASS: SHA-384 digest matches the FIPS 180-4 vector\n");
        }

        // The same transfer also copied the message; check it landed. A digest
        // engine fed correctly while the copy path is broken still fails here.
        volatile uint8_t *dst8 = (volatile uint8_t *)DMA_DST_ADDR;
        int msg_mismatches = 0;
        for (int i = 0; i < FIPS_MSG_LEN; i++) {
            if (dst8[i] != (uint8_t)kFips1804Msg[i]) {
                printf("  ERROR: SHA-384 copy mismatch at byte %d: got 0x%02x want 0x%02x\n", i,
                       dst8[i], (uint8_t)kFips1804Msg[i]);
                errors++;
                msg_mismatches++;
            }
        }
        if (msg_mismatches == 0) {
            printf("  PASS: SHA-384 pass also copied the message to DCCM intact\n");
        }
    }

    //==========================================================================
    // Step 7: Multi-chunk inline SHA-256 over the same FIPS message
    //==========================================================================
    // The passes above are single-chunk: CHUNK_DATA_SIZE == TOTAL_DATA_SIZE, so
    // the hash engine sees the whole message in one go. Here the same 56 bytes
    // are carried as two 28-byte chunks, and the digest must still be the
    // published SHA-256 of the whole message -- a hash that restarted per chunk,
    // or that dropped the tail, produces a different digest and fails.
    //
    // Interrupts are disabled for this pass: the ISR clears STATUS.chunk_done,
    // and chunk pacing has to read that bit.
    printf("\n=== Secure DMA multi-chunk SHA-256 (FIPS 180-4 vector) ===\n");
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR, 0);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, FIPS_MSG_LEN);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, FIPS_CHUNK_LEN);

    uint32_t mc_status = 0;
    uint32_t mc_chunks = 0;
    uint32_t mc_initial = SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm;
    for (uint32_t guard = 0; guard < 16u; guard++) {
        secure_dma__CONTROL_t mc_ctrl = {.f = {.OPCODE = OPCODE_SHA256, .DIGEST_SWAP = 1, .GO = 1}};
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, mc_ctrl.w | mc_initial);

        int t = 200000;
        do {
            mc_status = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        } while (!(mc_status & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm |
                                SECURE_DMA__STATUS__CHUNK_DONE_bm)) &&
                 --t > 0);
        if (mc_status & SECURE_DMA__STATUS__ERROR_bm) break;
        mc_chunks++;
        if (mc_status & SECURE_DMA__STATUS__DONE_bm) break;
        // Clear chunk_done and continue the same transfer.
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, SECURE_DMA__STATUS__CHUNK_DONE_bm);
        mc_initial = 0;
    }

    uint32_t mc_err = READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (!(mc_status & SECURE_DMA__STATUS__DONE_bm) || mc_err != 0) {
        printf("  ERROR: multi-chunk SHA-256 did not complete (status 0x%x err 0x%x "
               "chunks %u)\n",
               mc_status, mc_err, (unsigned)mc_chunks);
        errors++;
    } else if (mc_chunks < 2u) {
        // Without this the pass could have been one chunk after all, and the
        // digest compare below would say nothing about chunking.
        printf("  ERROR: multi-chunk SHA-256 completed in %u chunk(s); 56 bytes at a "
               "28-byte chunk size must take at least 2\n",
               (unsigned)mc_chunks);
        errors++;
    } else {
        uint32_t hw256[SHA256_DIGEST_WORDS];
        for (int i = 0; i < SHA256_DIGEST_WORDS; i++) {
            hw256[i] = READ_REG(OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR(i));
        }
        char mc_hex[2 * SHA256_DIGEST_BYTES + 1];
        digest_to_hex((const uint8_t *)hw256, SHA256_DIGEST_BYTES, mc_hex);
        printf("  Chunks        = %u\n", (unsigned)mc_chunks);
        printf("  Computed (HW) = %s\n", mc_hex);
        printf("  Expected (NIST) = %s\n", kFips1804Sha256Hex);
        if (strcmp(mc_hex, kFips1804Sha256Hex) != 0) {
            printf("  ERROR: multi-chunk SHA-256 digest does not match the FIPS 180-4 "
                   "vector!\n");
            errors++;
        } else {
            printf("  PASS: multi-chunk SHA-256 digest matches the FIPS 180-4 vector "
                   "over %u chunks\n",
                   (unsigned)mc_chunks);
        }
    }
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, SECURE_DMA__STATUS__DONE_bm |
                                                           SECURE_DMA__STATUS__ERROR_bm |
                                                           SECURE_DMA__STATUS__CHUNK_DONE_bm);

    //==========================================================================
    // Step 8: DIGEST_SWAP is the only thing that changes between these two runs
    //==========================================================================
    // Every pass above sets DIGEST_SWAP=1. Nothing so far shows the bit does
    // anything: a DMA that ignored it would pass them all. Re-run the same
    // single-chunk SHA-256 with DIGEST_SWAP=0 and require each digest word to be
    // the byte-reverse of the swapped run. Equal words mean the bit is dead.
    printf("\n=== Secure DMA DIGEST_SWAP ===\n");

    uint32_t swapped[SHA256_DIGEST_WORDS];
    uint32_t unswapped[SHA256_DIGEST_WORDS];

    for (int pass = 0; pass < 2; pass++) {
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, FIPS_MSG_LEN);
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, FIPS_MSG_LEN);
        secure_dma__CONTROL_t sw_ctrl = {.f = {.OPCODE = OPCODE_SHA256,
                                               .DIGEST_SWAP = (pass == 0) ? 1u : 0u,
                                               .INITIAL_TRANSFER = 1,
                                               .GO = 1}};
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, sw_ctrl.w);

        uint32_t st = 0;
        int t = 200000;
        do {
            st = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        } while (!(st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) && --t > 0);

        uint32_t err = READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
        if (!(st & SECURE_DMA__STATUS__DONE_bm) || err != 0) {
            printf("  ERROR: DIGEST_SWAP=%d run did not complete (status 0x%x err 0x%x)\n",
                   (pass == 0) ? 1 : 0, st, err);
            errors++;
        } else {
            uint32_t *dst = (pass == 0) ? swapped : unswapped;
            for (int i = 0; i < SHA256_DIGEST_WORDS; i++) {
                dst[i] = READ_REG(OCH_SEP_TOP_SECURE_DMA_SHA2_DIGEST_0_BASE_ADDR(i));
            }
        }
        WRITE_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, SECURE_DMA__STATUS__DONE_bm |
                                                               SECURE_DMA__STATUS__ERROR_bm |
                                                               SECURE_DMA__STATUS__CHUNK_DONE_bm);
    }

    int swap_mismatches = 0;
    int swap_identical = 0;
    for (int i = 0; i < SHA256_DIGEST_WORDS; i++) {
        uint32_t w = unswapped[i];
        uint32_t rev = ((w & 0x000000FFu) << 24) | ((w & 0x0000FF00u) << 8) |
                       ((w & 0x00FF0000u) >> 8) | ((w & 0xFF000000u) >> 24);
        if (rev != swapped[i]) {
            printf("  ERROR: DIGEST_SWAP word %d: swapped 0x%08x, byte-reverse of "
                   "unswapped 0x%08x = 0x%08x\n",
                   i, swapped[i], w, rev);
            swap_mismatches++;
        }
        if (w == swapped[i]) swap_identical++;
    }
    if (swap_mismatches) {
        errors++;
    } else if (swap_identical == SHA256_DIGEST_WORDS) {
        // A palindromic digest would satisfy the reverse test without the bit
        // doing anything. Vanishingly unlikely, but it is the one way this
        // check could pass on a dead DIGEST_SWAP, so it is called out.
        printf("  ERROR: every digest word is unchanged by DIGEST_SWAP -- the bit "
               "appears to have no effect\n");
        errors++;
    } else {
        printf("  PASS: all %d digest words under DIGEST_SWAP=0 are the byte-reverse "
               "of the DIGEST_SWAP=1 run\n",
               SHA256_DIGEST_WORDS);
    }

    printf("\n=== Test Summary ===\n");

    if (errors == 0) {
        printf("All SHA-256 and SHA-384 hash tests PASSED\n");
        test_pass(0);
    } else {
        printf("FAILED: %d hash test(s) failed\n", errors);
        test_fail(errors);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
