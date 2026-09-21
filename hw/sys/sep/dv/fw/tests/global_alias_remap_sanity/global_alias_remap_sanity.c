/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// Global Alias Remap Sanity Test
//
// Tests the global alias address remapping feature of SEP for inbound traffic.
// With sep_global_base_addr = 0x2000_0000:
//   - External writes to 0x3000_0000 get remapped to 0x1000_0000 (SRAM)
//   - Formula: remapped_addr = incoming_addr - sep_global_base_addr + target_base
//   - 0x3000_0000 - 0x2000_0000 + 0 = 0x1000_0000
//
// Note: Addresses must be < EXTERNAL_TO_CHIPLET_BASE_ADDR (0x1_0000_0000) to
// route through SEP_LOCAL in the AXI demux and reach the remap unit.
//
// Test Flow:
//   1. CPU sets SEP_GLOBAL_BASE_ADDR to 0x2000_0000
//   2. CPU signals ready to Cocotb via scratch register
//   3. Cocotb performs external AXI writes to 0x1_3000_0000
//   4. Cocotb signals done via scratch register
//   5. CPU reads SRAM at local address 0x1000_0000 and verifies
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

//-----------------------------------------------------------------------------
// Global Alias Configuration
//-----------------------------------------------------------------------------

// Global base address to configure (external addresses start here).
// Must be < EXTERNAL_TO_CHIPLET_BASE_ADDR (0x1_0000_0000) to route through
// SEP_LOCAL path in the AXI demux and reach the global-to-local remap unit.
// Also must not overlap SMC range (0x4000_0000~0x8000_0000) configured in TB.
#define SEP_GLOBAL_BASE_ADDR_VALUE 0x20000000ULL

// Global address that Cocotb will write to.
// Remap: 0x3000_0000 - 0x2000_0000 + 0 = 0x1000_0000 (SRAM)
#define SEP_SRAM_GLOBAL_ADDR 0x30000000ULL

// Local SRAM address (where writes will be remapped to)
#define SEP_SRAM_LOCAL_BASE SEP_TOP_SEP_SRAM_BASE_ADDR // 0x1000_0000

// SEP CPU Control register for global base address
#define SEP_GLOBAL_BASE_ADDR_REG \
    SEP_TOP_SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_BASE_ADDR // 0x10A300C0

// Scratch registers for CPU <-> Cocotb synchronization
#define SYNC_CPU_READY_REG SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)   // 0x10802000
#define SYNC_COCOTB_DONE_REG SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1) // 0x10802008

// Synchronization markers
#define CPU_READY_MARKER 0x12345678
#define COCOTB_DONE_MARKER 0x87654321

// Poll timeout (in iterations)
#define POLL_TIMEOUT 100000

//-----------------------------------------------------------------------------
// Test Patterns (must match Cocotb test)
//-----------------------------------------------------------------------------

// Test pattern offsets from SRAM base (in bytes)
static const uint32_t test_offsets[] = {0x00, 0x10, 0x20, 0x30};

// Expected test patterns at each offset
static const uint32_t test_patterns[] = {0xDEADBEEF, 0xCAFEBABE, 0x55AA55AA, 0xFF00FF00};

#define NUM_PATTERNS (sizeof(test_patterns) / sizeof(test_patterns[0]))

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
// Test: Configure Global Base Address
//-----------------------------------------------------------------------------
static int test_config_global_base(void) {
    printf("\n--- Test: Configure Global Base Address ---\n");

    // Read current value
    uint64_t current_base = READ_REG64(SEP_GLOBAL_BASE_ADDR_REG);
    printf("  Current SEP_GLOBAL_BASE_ADDR: 0x%llX\n", (unsigned long long)current_base);

    // Write new global base address
    printf("  Setting SEP_GLOBAL_BASE_ADDR to 0x%llX...\n",
           (unsigned long long)SEP_GLOBAL_BASE_ADDR_VALUE);
    WRITE_REG64(SEP_GLOBAL_BASE_ADDR_REG, SEP_GLOBAL_BASE_ADDR_VALUE);

    // Verify the write
    uint64_t readback = READ_REG64(SEP_GLOBAL_BASE_ADDR_REG);
    printf("  Readback: 0x%llX\n", (unsigned long long)readback);

    if (readback != SEP_GLOBAL_BASE_ADDR_VALUE) {
        printf("  ERROR: Write verification failed!\n");
        printf("    Expected: 0x%llX\n", (unsigned long long)SEP_GLOBAL_BASE_ADDR_VALUE);
        printf("    Got:      0x%llX\n", (unsigned long long)readback);
        return 0;
    }

    printf("  Global base address configured successfully\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Signal Ready and Wait for Cocotb
//-----------------------------------------------------------------------------
static int test_sync_with_cocotb(void) {
    printf("\n--- Test: Synchronization with Cocotb ---\n");

    // Clear sync registers first
    WRITE_REG(SYNC_CPU_READY_REG, 0);
    WRITE_REG(SYNC_COCOTB_DONE_REG, 0);

    // Signal to Cocotb that CPU is ready
    printf("  Signaling CPU ready (0x%08X) to SCRATCH_0...\n", CPU_READY_MARKER);
    WRITE_REG(SYNC_CPU_READY_REG, CPU_READY_MARKER);

    // Wait for Cocotb to signal completion
    printf("  Waiting for Cocotb done marker at SCRATCH_1...\n");
    uint32_t poll_count = 0;
    uint32_t done_val = 0;

    while (poll_count < POLL_TIMEOUT) {
        done_val = READ_REG(SYNC_COCOTB_DONE_REG);
        if (done_val == COCOTB_DONE_MARKER) {
            printf("  Cocotb signaled done after %u polls\n", poll_count);
            return 1;
        }
        poll_count++;
    }

    printf("  ERROR: Timeout waiting for Cocotb (polls=%u, last_val=0x%08X)\n", poll_count,
           done_val);
    return 0;
}

//-----------------------------------------------------------------------------
// Test: Verify SRAM Contents
//-----------------------------------------------------------------------------
static int test_verify_sram(void) {
    printf("\n--- Test: Verify SRAM Contents ---\n");

    volatile uint32_t *sram_base = (volatile uint32_t *)SEP_SRAM_LOCAL_BASE;
    int errors = 0;

    printf("  Verifying %u patterns at SRAM base 0x%08X...\n", (unsigned)NUM_PATTERNS,
           SEP_SRAM_LOCAL_BASE);

    for (unsigned i = 0; i < NUM_PATTERNS; i++) {
        uint32_t offset = test_offsets[i];
        uint32_t word_idx = offset / 4; // Convert byte offset to word index
        uint32_t expected = test_patterns[i];
        uint32_t actual = sram_base[word_idx];

        printf("    Offset 0x%02X: expected=0x%08X, actual=0x%08X", offset, expected, actual);

        if (actual == expected) {
            printf(" [OK]\n");
        } else {
            printf(" [MISMATCH]\n");
            errors++;
        }
    }

    if (errors == 0) {
        printf("  All %u patterns verified successfully\n", (unsigned)NUM_PATTERNS);
        return 1;
    } else {
        printf("  ERROR: %d pattern mismatches detected\n", errors);
        return 0;
    }
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------
int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  SEP Global Alias Remap Sanity Test\n");
    printf("========================================\n");
    printf("\n");
    printf("Global Alias Remap Configuration:\n");
    printf("  sep_global_base_addr: 0x%llX\n", (unsigned long long)SEP_GLOBAL_BASE_ADDR_VALUE);
    printf("  External write addr:  0x%llX\n", (unsigned long long)SEP_SRAM_GLOBAL_ADDR);
    printf("  Remapped to local:    0x%08X (SRAM)\n", SEP_SRAM_LOCAL_BASE);
    printf("\n");
    printf("Remap formula:\n");
    printf("  0x%llX - 0x%llX + 0 = 0x%08X\n", (unsigned long long)SEP_SRAM_GLOBAL_ADDR,
           (unsigned long long)SEP_GLOBAL_BASE_ADDR_VALUE, SEP_SRAM_LOCAL_BASE);
    printf("\n");

    // Step 1: Configure global base address
    report_test("Configure Global Base Address", test_config_global_base());

    // Step 2: Signal ready and wait for Cocotb to perform external writes
    report_test("Sync with Cocotb", test_sync_with_cocotb());

    // Step 3: Verify SRAM contents written by Cocotb
    report_test("Verify SRAM Contents", test_verify_sram());

    // Print summary
    printf("\n========================================\n");
    printf("          Test Summary\n");
    printf("========================================\n");
    printf("Total:    %d tests\n", test_count);
    printf("Passed:   %d\n", pass_count);

    if (fail_count == 0) {
        printf("\n*** ALL TESTS PASSED ***\n");
        test_pass(0);
    } else {
        printf("Errors:   %d\n", fail_count);
        printf("\n*** SOME TESTS HAD ERRORS ***\n");
        test_fail(fail_count);
    }

    // Keep CPU alive after signaling completion
    while (1) {
        __asm__("wfi");
    }
}
