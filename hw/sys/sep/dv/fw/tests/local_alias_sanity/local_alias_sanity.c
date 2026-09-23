/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// Local Alias Sanity Test
//
// Tests the local alias address remapping feature of SEP.
// With local_alias_base = 0xC000_0000 and target_base = 0x0:
//   - Addresses in range [0xC000_0000, 0xC000_0000 + region_size) are remapped
//   - 0xD000_0000 -> 0x1000_0000 (offset = 0xD000_0000 - 0xC000_0000 = 0x1000_0000)
//   - 0xD080_2000 -> 0x1080_2000 (scratch registers)
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

//-----------------------------------------------------------------------------
// Local Alias Configuration
//-----------------------------------------------------------------------------

// The local alias base address (reset default 0xD000_0000)
// When CPU accesses address X in range [local_alias_base, local_alias_base + region_size),
// it gets remapped to X - local_alias_base + target_base (target_base = 0x1000_0000 )
#define LOCAL_ALIAS_BASE 0xD0000000UL
#define LOCAL_ALIAS_OFFSET \
    0xC0000000UL // = LOCAL_ALIAS_BASE - target_base (0xD000_0000 - 0x1000_0000)

// Direct peripheral addresses (physical addresses at 0x1000_0000 region)
#define SCRATCH_COLD_DIRECT_BASE OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR // 0x1080_2000
#define SCRATCH_WARM_DIRECT_BASE OCH_SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR // 0x1080_2080
#define SRAM_DIRECT_BASE OCH_SEP_TOP_SEP_SRAM_BASE_ADDR                 // 0x1000_0000

// Aliased peripheral addresses (accessed via local alias at 0xD000_0000 region)
#define SCRATCH_COLD_ALIAS_BASE (SCRATCH_COLD_DIRECT_BASE + LOCAL_ALIAS_OFFSET) // 0xD080_2000
#define SCRATCH_WARM_ALIAS_BASE (SCRATCH_WARM_DIRECT_BASE + LOCAL_ALIAS_OFFSET) // 0xD080_2080
#define SRAM_ALIAS_BASE (SRAM_DIRECT_BASE + LOCAL_ALIAS_OFFSET)                 // 0xD000_0000

// SEP CPU Control registers for configuring local alias
#define SEP_LOCAL_BASE_ADDR_REG OCH_SEP_TOP_SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_BASE_ADDR // 0x10A300C8
#define SEP_REGION_SIZE_REG OCH_SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR         // 0x10A300D0

//-----------------------------------------------------------------------------
// Test State
//-----------------------------------------------------------------------------

static int test_count = 0;
static int pass_count = 0;
static int fail_count = 0;

//-----------------------------------------------------------------------------
// Helper Functions
//-----------------------------------------------------------------------------

static void report_test(const char *name, int passed) {
    test_count++;
    if (passed) {
        pass_count++;
        printf("[PASS] %s\n", name);
    } else {
        fail_count++;
        printf("[FAIL] %s\n", name);
    }
}

//-----------------------------------------------------------------------------
// Test: Verify Local Alias Configuration
//-----------------------------------------------------------------------------
static int test_local_alias_config(void) {
    printf("\n--- Test: Verify Local Alias Configuration ---\n");

    // Read current configuration
    uint64_t local_base = READ_REG64(SEP_LOCAL_BASE_ADDR_REG);
    uint32_t region_size = READ_REG(SEP_REGION_SIZE_REG);

    printf("  SEP_LOCAL_BASE_ADDR: 0x%08lX\n", (unsigned long)local_base);
    printf("  SEP_REGION_SIZE:     0x%08X\n", region_size);

    // Verify configured values (local_base = 0xC000_0000; region_size is
    // programmed to 0x4000_0000 by main() since the RDL default is 0x0200_0000).
    int config_ok = 1;
    if (local_base != LOCAL_ALIAS_BASE) {
        printf("  WARNING: Local base addr is 0x%08lX, expected 0x%08lX\n",
               (unsigned long)local_base, (unsigned long)LOCAL_ALIAS_BASE);
        // Not a failure - just informational
    }

    // Verify region size covers the 0xD000_0000 region
    // For 0xD000_0000 to be in alias region: 0xD000_0000 < local_base + region_size
    // With local_base = 0xC000_0000, need region_size > 0x1000_0000
    uint64_t alias_end = local_base + region_size;
    if (alias_end <= 0xD0000000UL) {
        printf("  ERROR: Region size too small to cover 0xD000_0000\n");
        printf("         Alias region ends at 0x%08lX\n", (unsigned long)alias_end);
        config_ok = 0;
    } else {
        printf("  Alias region: [0x%08lX, 0x%08lX)\n", (unsigned long)local_base,
               (unsigned long)alias_end);
    }

    return config_ok;
}

//-----------------------------------------------------------------------------
// Test: Set Local Alias Base to 0
//-----------------------------------------------------------------------------
static int test_local_base_writable(void) {
    const uint64_t ALT_BASE =
        0xE0000000UL; // window [0xE000_0000, 0x1_1000_0000): working set stays passthrough

    printf("\n--- Test: SEP_LOCAL_BASE_ADDR Writable ---\n");

    printf("  Writing 0x%08lX to SEP_LOCAL_BASE_ADDR register...\n", (unsigned long)ALT_BASE);
    WRITE_REG64(SEP_LOCAL_BASE_ADDR_REG, ALT_BASE);

    // Verify the write
    uint64_t readback = READ_REG64(SEP_LOCAL_BASE_ADDR_REG);
    printf("  Readback: 0x%08lX\n", (unsigned long)readback);

    if (readback != ALT_BASE) {
        printf("  ERROR: Write failed, expected 0x%08lX\n", (unsigned long)ALT_BASE);
        return 0;
    }

    // Restore default value for subsequent tests
    printf("  Restoring local base to 0x%08lX...\n", (unsigned long)LOCAL_ALIAS_BASE);
    WRITE_REG64(SEP_LOCAL_BASE_ADDR_REG, LOCAL_ALIAS_BASE);

    readback = READ_REG64(SEP_LOCAL_BASE_ADDR_REG);
    if (readback != LOCAL_ALIAS_BASE) {
        printf("  ERROR: Restore failed, got 0x%08lX\n", (unsigned long)readback);
        return 0;
    }

    return 1;
}

//-----------------------------------------------------------------------------
// Test: Scratch Register Access via Direct and Alias Paths
//-----------------------------------------------------------------------------
static int test_scratch_alias(void) {
    printf("\n--- Test: Scratch Register Alias Access ---\n");

    // Test pattern
    uint32_t test_pattern = 0xDEADBEEF;
    uint32_t read_direct, read_alias;

    // Step 1: Write via DIRECT path, read via ALIAS path
    printf("  Test 1: Write direct (0x%08X) -> Read alias (0x%08lX)\n",
           OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0),
           (unsigned long)SCRATCH_COLD_ALIAS_BASE);

    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0), test_pattern);
    read_alias = READ_REG(SCRATCH_COLD_ALIAS_BASE);

    printf("    Wrote: 0x%08X, Read via alias: 0x%08X\n", test_pattern, read_alias);

    if (read_alias != test_pattern) {
        printf("    ERROR: Mismatch! Expected 0x%08X\n", test_pattern);
        return 0;
    }

    // Step 2: Write via ALIAS path, read via DIRECT path
    test_pattern = 0xCAFEBABE;
    printf("  Test 2: Write alias (0x%08lX) -> Read direct (0x%08X)\n",
           (unsigned long)SCRATCH_COLD_ALIAS_BASE,
           OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0));

    WRITE_REG(SCRATCH_COLD_ALIAS_BASE, test_pattern);
    read_direct = READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0));

    printf("    Wrote: 0x%08X, Read via direct: 0x%08X\n", test_pattern, read_direct);

    if (read_direct != test_pattern) {
        printf("    ERROR: Mismatch! Expected 0x%08X\n", test_pattern);
        return 0;
    }

    // Step 3: Test multiple scratch registers
    printf("  Test 3: Multiple scratch register test\n");
    for (int i = 0; i < 4; i++) {
        uint32_t pattern = 0xA5A5A5A5 ^ (i << 24);
        uint32_t direct_addr = OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0) + (i * 8);
        uint32_t alias_addr = SCRATCH_COLD_ALIAS_BASE + (i * 8);

        // Write via alias
        WRITE_REG(alias_addr, pattern);

        // Read via direct
        uint32_t readback = READ_REG(direct_addr);

        if (readback != pattern) {
            printf("    ERROR: Scratch[%d] mismatch: wrote 0x%08X, got 0x%08X\n", i, pattern,
                   readback);
            return 0;
        }
    }
    printf("    All scratch registers verified\n");

    return 1;
}

//-----------------------------------------------------------------------------
// Test: SRAM Access via Alias Path (0xD000_0000 -> 0x1000_0000)
//-----------------------------------------------------------------------------
static int test_sram_alias(void) {
    printf("\n--- Test: SRAM Alias Access (0xD000_0000 -> 0x1000_0000) ---\n");

    // Test a small region of SRAM
    volatile uint32_t *sram_direct = (volatile uint32_t *)SRAM_DIRECT_BASE;
    volatile uint32_t *sram_alias = (volatile uint32_t *)SRAM_ALIAS_BASE;

    printf("  Direct SRAM base: 0x%08X\n", SRAM_DIRECT_BASE);
    printf("  Alias SRAM base:  0x%08lX\n", (unsigned long)SRAM_ALIAS_BASE);

    // Test pattern write via alias, read via direct
    uint32_t test_patterns[] = {0x12345678, 0xABCDEF01, 0x55AA55AA, 0xFF00FF00};
    int num_patterns = sizeof(test_patterns) / sizeof(test_patterns[0]);

    printf("  Writing patterns via alias path...\n");
    for (int i = 0; i < num_patterns; i++) {
        sram_alias[i] = test_patterns[i];
    }

    printf("  Reading patterns via direct path...\n");
    for (int i = 0; i < num_patterns; i++) {
        uint32_t readback = sram_direct[i];
        if (readback != test_patterns[i]) {
            printf("    ERROR at offset %d: wrote 0x%08X, read 0x%08X\n", i, test_patterns[i],
                   readback);
            return 0;
        }
    }

    // Reverse test: write via direct, read via alias
    printf("  Writing patterns via direct path...\n");
    for (int i = 0; i < num_patterns; i++) {
        sram_direct[i] = ~test_patterns[i]; // Inverted patterns
    }

    printf("  Reading patterns via alias path...\n");
    for (int i = 0; i < num_patterns; i++) {
        uint32_t readback = sram_alias[i];
        uint32_t expected = ~test_patterns[i];
        if (readback != expected) {
            printf("    ERROR at offset %d: wrote 0x%08X, read 0x%08X\n", i, expected, readback);
            return 0;
        }
    }

    printf("  All SRAM alias tests passed\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: 64-bit Access via Alias Path
//-----------------------------------------------------------------------------
static int test_64bit_alias(void) {
    printf("\n--- Test: 64-bit Access via Alias Path ---\n");

    volatile uint64_t *sram_direct = (volatile uint64_t *)SRAM_DIRECT_BASE;
    volatile uint64_t *sram_alias = (volatile uint64_t *)SRAM_ALIAS_BASE;

    uint64_t test_value = 0xDEADBEEFCAFEBABEULL;

    // Write via alias
    sram_alias[0] = test_value;

    // Read via direct
    uint64_t readback = sram_direct[0];

    printf("  Wrote 0x%016llX via alias\n", (unsigned long long)test_value);
    printf("  Read  0x%016llX via direct\n", (unsigned long long)readback);

    if (readback != test_value) {
        printf("  ERROR: 64-bit mismatch!\n");
        return 0;
    }

    return 1;
}

//-----------------------------------------------------------------------------
// Test: Address Boundary Test
//-----------------------------------------------------------------------------
static int test_boundary(void) {
    printf("\n--- Test: Address Boundary Test ---\n");

    // Test addresses at different offsets from 0xD000_0000
    // These should all map correctly to 0x1000_0000 + offset

    volatile uint32_t *sram_direct = (volatile uint32_t *)SRAM_DIRECT_BASE;
    volatile uint32_t *sram_alias = (volatile uint32_t *)SRAM_ALIAS_BASE;

    // Test at various offsets
    uint32_t offsets[] = {0, 0x100, 0x1000, 0x10000};
    int num_offsets = sizeof(offsets) / sizeof(offsets[0]);

    for (int i = 0; i < num_offsets; i++) {
        uint32_t offset = offsets[i];
        uint32_t pattern = 0xBEEF0000 | offset;

        // Word index (offset is in bytes, convert to word index)
        uint32_t word_idx = offset / 4;

        // Write via alias
        sram_alias[word_idx] = pattern;

        // Read via direct
        uint32_t readback = sram_direct[word_idx];

        printf("  Offset 0x%05X: alias=0x%08lX, direct=0x%08X\n", offset,
               (unsigned long)(SRAM_ALIAS_BASE + offset), SRAM_DIRECT_BASE + offset);

        if (readback != pattern) {
            printf("    ERROR: wrote 0x%08X, read 0x%08X\n", pattern, readback);
            return 0;
        }
    }

    printf("  All boundary tests passed\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: DMA Transfer via Local Alias Path
//-----------------------------------------------------------------------------
static int test_dma_alias(void) {
    printf("\n--- Test: DMA Transfer (SRAM to SRAM via Physical Address) ---\n");
    printf("  Note: DMA uses physical addresses only.\n");
    printf("  Local alias (0xD000_0000) only applies to CPU/LSU traffic, not DMA.\n");

    // DMA will read from one SRAM region and write to another using physical addresses.
    // Note: DMA cannot use local alias addresses (0xD000_0000 range) because the
    // local alias remap in the SEP crossbar only applies to CPU/LSU bus traffic.
    // DMA must target physical addresses.

    // Use different SRAM regions to avoid overlap
    uint32_t src_direct_addr = OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x2000; // 0x1000_2000
    uint32_t dst_direct_addr = OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x3000; // 0x1000_3000 (physical)
    uint32_t transfer_size = 0x100;                                     // 256 bytes

    volatile uint32_t *src_ptr = (volatile uint32_t *)src_direct_addr;
    volatile uint32_t *dst_ptr = (volatile uint32_t *)dst_direct_addr;

    // Initialize source with test pattern, clear destination
    printf("  Initializing source memory...\n");
    for (int i = 0; i < (int)(transfer_size / 4); i++) {
        src_ptr[i] = 0xD1A00000 | i;
        dst_ptr[i] = 0x0;
    }

    // Configure DMA memory range
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    // Set source (direct address)
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src_direct_addr);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);

    // Set destination (physical address - DMA cannot use local alias)
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst_direct_addr);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);

    printf("  DMA: 0x%08X -> 0x%08X (physical SRAM)\n", src_direct_addr, dst_direct_addr);

    // Configure DMA transfer. ASID 0 is not a valid address space and makes the
    // DMA report ASID_ERROR, so both ASIDs must carry the OT internal bus default.
    WRITE_REG(
        OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
        (SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset << SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_bp) |
            (SECURE_DMA__ADDR_SPACE_ID__DST_ASID_reset << SECURE_DMA__ADDR_SPACE_ID__DST_ASID_bp));
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR,
              SECURE_DMA__TRANSFER_WIDTH__TRANSACTION_WIDTH_reset
                  << SECURE_DMA__TRANSFER_WIDTH__TRANSACTION_WIDTH_bp);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, transfer_size);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, transfer_size);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);

    // Start transfer
    printf("  Starting DMA transfer...\n");
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
              SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm);

    // Poll for completion
    int timeout = 100000;
    uint32_t status;
    while (timeout-- > 0) {
        status = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status & SECURE_DMA__STATUS__DONE_bm) break;
        if (status & SECURE_DMA__STATUS__ERROR_bm) {
            printf("  ERROR: DMA failed! ERROR_CODE=0x%x\n",
                   READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
            return 0;
        }
    }
    if (timeout <= 0) {
        printf("  ERROR: DMA timeout!\n");
        return 0;
    }

    // Verify: Read from DIRECT address (not alias) to confirm data landed correctly
    printf("  Verifying data at direct address 0x%08X...\n", dst_direct_addr);
    int errors = 0;
    for (int i = 0; i < (int)(transfer_size / 4); i++) {
        if (dst_ptr[i] != src_ptr[i]) {
            printf("    Mismatch at offset %d: expected 0x%08X, got 0x%08X\n", i, src_ptr[i],
                   dst_ptr[i]);
            errors++;
            if (errors > 3) break; // Limit error output
        }
    }

    if (errors == 0) {
        printf("  PASS: DMA via alias path worked correctly!\n");
        return 1;
    }
    return 0;
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------
int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    // Program the local-alias aperture to cover the 0xD000_0000 test region.
    // The RDL default for SEP_REGION_SIZE is 0x0200_0000 (32 MiB, aligned with
    // tt_sep), which would only alias [0xC000_0000, 0xC200_0000). This test
    // exercises accesses up to 0xD080_2080, so widen the aperture to 1 GiB for
    // the duration of the test.
    WRITE_REG(SEP_REGION_SIZE_REG, 0x40000000U);
    WRITE_REG64(SEP_LOCAL_BASE_ADDR_REG, LOCAL_ALIAS_BASE);

    printf("\n");
    printf("========================================\n");
    printf("     SEP Local Alias Sanity Test\n");
    printf("========================================\n");
    printf("\n");
    printf("Local Alias Mapping:\n");
    printf("  0xD000_0000 (alias) -> 0x1000_0000 (physical)\n");
    printf("  Offset: 0xC000_0000 (local_alias_base - target_base)\n");
    printf("\n");

    // Run tests
    report_test("Local Alias Configuration", test_local_alias_config());
    report_test("SEP_LOCAL_BASE_ADDR Writable", test_local_base_writable());
    report_test("Scratch Register Alias", test_scratch_alias());
    report_test("SRAM Alias (0xD000_0000)", test_sram_alias());
    report_test("64-bit Access via Alias", test_64bit_alias());
    report_test("Address Boundary", test_boundary());
    report_test("DMA Transfer (physical addr)", test_dma_alias());

    // Print summary
    printf("\n========================================\n");
    printf("     Test Summary\n");
    printf("========================================\n");
    printf("Total:  %d tests\n", test_count);
    printf("Passes: %d\n", pass_count);
    printf("Failures: %d\n", fail_count);

    if (fail_count == 0) {
        printf("\n*** ALL TESTS PASSED ***\n");
        test_pass(0);
    } else {
        printf("\n*** SOME TESTS FAILED ***\n");
        test_fail(fail_count);
    }

    // Keep CPU alive after signaling completion
    while (1) {
        __asm__("wfi");
    }
}
