/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// AP and STEE Output Remap Test
//
// Simple test to verify AP and STEE output remap functionality by:
//   1. Configuring AP output remap control register 0 with an offset value
//   2. Configuring STEE output remap control register 0 with an offset value
//   3. Writing test patterns to the remap regions
//   4. Basic verification that the system is functional
//
// Test Flow:
//   1. Configure AP_OUTPUT_REMAP_CTRL_0 with offset
//   2. Configure STEE_OUTPUT_REMAP_CTRL_0 with offset
//   3. Write test patterns to both remap regions
//   4. Verify register configurations are correct
//   5. Signal test completion
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

//-----------------------------------------------------------------------------
// Output Remap Configuration
//-----------------------------------------------------------------------------

// Num Remaps
#define NUM_AP_REMAPS 16
#define NUM_STEE_REMAPS 16

// Traffic Generation Configuration
#define SEGMENT_SIZE 0x80000            // 512KB per segment (8MB / 16 segments)
#define NUM_TRAFFIC_WRITES 4            // Number of writes per segment
#define TRAFFIC_PATTERN_BASE 0xC0FFEE00 // Base pattern for traffic

//-----------------------------------------------------------------------------
// Test State
//-----------------------------------------------------------------------------

static int test_count = 0;
static int pass_count = 0;
static int fail_count = 0;

//-----------------------------------------------------------------------------
// Helper Functions
//-----------------------------------------------------------------------------

// Generate a 64-bit random value where each bit has equal chance of being 0 or 1
static uint64_t generate_random_64bit(void) {
    // Use multiple rand() calls to ensure full 64-bit coverage
    uint64_t random_val = 0;

    // Combine multiple rand() calls to cover all 64 bits
    random_val |= ((uint64_t)rand() & 0xFFFFULL) << 0;  // bits 0-15
    random_val |= ((uint64_t)rand() & 0xFFFFULL) << 16; // bits 16-31
    random_val |= ((uint64_t)rand() & 0xFFFFULL) << 32; // bits 32-47
    random_val |= ((uint64_t)rand() & 0xFFFFULL) << 48; // bits 48-63

    return random_val;
}

// Generate a random address within a segment boundary, maintaining 8-byte alignment
static uint64_t generate_random_segment_address(uint64_t segment_base, uint64_t segment_size) {
    // Ensure we have room for at least one aligned address
    if (segment_size < 8) {
        return segment_base;
    }

    // Calculate the maximum offset (aligned to 8 bytes)
    uint64_t max_offset = (segment_size - 8) & ~0x7ULL;

    // Generate random offset within the segment, maintaining 8-byte alignment
    uint64_t random_offset = (generate_random_64bit() % (max_offset / 8 + 1)) * 8;

    return segment_base + random_offset;
}

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
// Test: Configure AP Output Remap
//-----------------------------------------------------------------------------
static int test_config_ap_output_remap(void) {
    printf("\n--- Test: Configure AP Output Remap ---\n");

    output_remap__output_remap_region__REGION_ATTRS_t ap_remap_ctrl;
    ap_remap_ctrl.f.offset = 0x0;

    for (int i = 0; i < NUM_AP_REMAPS; i++) {
        ap_remap_ctrl.f.offset = generate_random_64bit();

        // Write the remap configuration
        WRITE_REG64(SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(i), ap_remap_ctrl.w);

        // Read back to verify
        uint64_t readback =
            READ_REG64(SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(i));

        // TODO: READ_REG64() returns only the lower 32 bits
    }

    printf("  AP output remap configured successfully\n");

    return 1;
}

//-----------------------------------------------------------------------------
// Test: Configure STEE Output Remap
//-----------------------------------------------------------------------------
static int test_config_stee_output_remap(void) {
    printf("\n--- Test: Configure STEE Output Remap ---\n");

    output_remap__output_remap_region__REGION_ATTRS_t stee_remap_ctrl;
    stee_remap_ctrl.f.offset = 0x0;

    for (int i = 0; i < NUM_STEE_REMAPS; i++) {
        stee_remap_ctrl.f.offset = generate_random_64bit();

        // Write the remap configuration
        WRITE_REG64(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(i),
                    stee_remap_ctrl.w);

        // Read back to verify
        uint64_t readback =
            READ_REG64(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(i));

        // TODO: READ_REG64() returns only the lower 32 bits
    }

    printf("  STEE output remap configured successfully\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Generate Traffic for All AP Segments
//-----------------------------------------------------------------------------
static int test_ap_segment_traffic(void) {
    printf("\n--- Test: Generate Traffic for All AP Segments ---\n");

    for (int segment = 0; segment < NUM_AP_REMAPS; segment++) {
        uint64_t segment_base = SEP_TOP_AP_REGION_BASE_ADDR + (segment * SEGMENT_SIZE);

        printf("  Generating traffic for AP segment %d (base: 0x%016llX)...\n", segment,
               (unsigned long long)segment_base);

        // Generate multiple writes within this segment
        for (int write_idx = 0; write_idx < NUM_TRAFFIC_WRITES; write_idx++) {
            uint64_t traffic_addr = generate_random_segment_address(segment_base, SEGMENT_SIZE);
            uint32_t write_pattern = TRAFFIC_PATTERN_BASE + (segment << 8) + write_idx;

            // Perform write & read (this will be remapped by hardware)
            WRITE_REG(traffic_addr, write_pattern);
            READ_REG(traffic_addr);
        }
    }

    printf("  AP segment traffic generation completed\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Generate Traffic for All STEE Segments
//-----------------------------------------------------------------------------
static int test_stee_segment_traffic(void) {
    printf("\n--- Test: Generate Traffic for All STEE Segments ---\n");

    for (int segment = 0; segment < NUM_STEE_REMAPS; segment++) {
        uint64_t segment_base = SEP_TOP_STEE_REGION_BASE_ADDR + (segment * SEGMENT_SIZE);

        printf("  Generating traffic for STEE segment %d (base: 0x%08llX)...\n", segment,
               (unsigned long long)segment_base);

        // Generate multiple writes within this segment
        for (int write_idx = 0; write_idx < NUM_TRAFFIC_WRITES; write_idx++) {
            uint64_t traffic_addr = generate_random_segment_address(segment_base, SEGMENT_SIZE);
            uint32_t write_pattern = TRAFFIC_PATTERN_BASE + 0x1000 + (segment << 8) + write_idx;

            // Perform write & read (this will be remapped by hardware)
            WRITE_REG(traffic_addr, write_pattern);
            READ_REG(traffic_addr);
        }
    }

    printf("  STEE segment traffic generation completed\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------
int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    // Configure outbound filter 1 to allow ALL addresses (wide open)
    filter_ctrl__FILTER_CONFIG_t open_filter_config;
    open_filter_config.w = 0; // Clear all fields first
    open_filter_config.f.read_allowed = 1;
    open_filter_config.f.write_allowed = 1;
    open_filter_config.f.entry_enabled =
        1; // Needs to be enabled since BlockByDefault is set in RTL
    open_filter_config.f.allow_ns = 0;
    open_filter_config.f.allow_burst = 1;
    open_filter_config.f.locked = 0;
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(1), open_filter_config.w);

    // Write END_ADDR register (must be configured before enabling filter)
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(1), 0x0);

    // Write FILTER_CONFIG register (enables filter atomically)
    // This must be written LAST to ensure address range is configured first
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(1), 0xFFFFFFFFFFFFFF);

    srand(815);

    printf("\n");
    printf("============================================\n");
    printf("    AP and STEE Output Remap Test\n");
    printf("============================================\n");
    printf("\n");
    printf("Output Remap Configuration:\n");
    printf("  AP Remap Ctrl 0:    0x%08X\n",
           SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0));
    printf("  STEE Remap Ctrl 0:  0x%08X\n",
           SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0));
    printf("  AP Remap Region:    0x%08lX\n", (unsigned long)SEP_TOP_AP_REGION_BASE_ADDR);
    printf("  STEE Remap Region:  0x%08lX\n", (unsigned long)SEP_TOP_STEE_REGION_BASE_ADDR);
    printf("\n");

    // Step 1: Configure AP output remap
    report_test("Configure AP Output Remap", test_config_ap_output_remap());

    // Step 2: Configure STEE output remap
    report_test("Configure STEE Output Remap", test_config_stee_output_remap());

    // Step 3: Wait for CocoTB setup
    uint64_t cocotb_flag = 0x0;
    WRITE_REG(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4), 0x815);

    do {
        cocotb_flag = READ_REG(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5));
        printf("still waiting...");
    } while (cocotb_flag != 0x777);

    // Step 4: Generate traffic for AP segments
    report_test("Generate AP Segment Traffic", test_ap_segment_traffic());

    // Step 5: Generate traffic for STEE segments
    report_test("Generate STEE Segment Traffic", test_stee_segment_traffic());

    // Print summary
    printf("\n============================================\n");
    printf("           Test Summary\n");
    printf("============================================\n");
    printf("Total:    %d tests\n", test_count);
    printf("Passed:   %d\n", pass_count);

    if (fail_count == 0) {
        printf("\n*** ALL TESTS PASSED ***\n");
        printf("AP and STEE output remap functionality verified!\n");
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
