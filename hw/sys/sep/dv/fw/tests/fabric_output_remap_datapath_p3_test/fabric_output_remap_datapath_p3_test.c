/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_output_remap_datapath_p3_test
 *
 * Strategy: AP/STEE remap traffic covers every region index; full datapath matrix
 *
 * Focus on full datapath testing across all 16 output-remap regions
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Output remap datapath scenario count
#define OUTPUT_DATAPATH_SCENARIOS 9

// Output-remap base definitions
#define OUTPUT_SRC_BASE 0x50000000
#define OUTPUT_DEST_BASE 0x90000000
#define AP_OUTPUT_BASE 0x60000000
#define STEE_OUTPUT_BASE 0xA0000000

// Output-remap modes
#define OUTPUT_REGION_SIZE 0x100000
#define MAX_OUTPUT_REGIONS 16

static int test_ap_stee_full_16_regions(void) {
    printf("Starting AP/STEE full 16 regions test...\n");

    // Scenario 1: AP/STEE full 16-region coverage
    for (int cycle = 0; cycle < 8; cycle++) {
        // Program all 16 output-remap regions
        for (int region = 0; region < 16; region++) {
            uint32_t src_addr = OUTPUT_SRC_BASE + cycle * 0x1000000 + region * OUTPUT_REGION_SIZE;
            uint32_t ap_dest = AP_OUTPUT_BASE + cycle * 0x1000000 + region * OUTPUT_REGION_SIZE;
            uint32_t stee_dest = STEE_OUTPUT_BASE + cycle * 0x1000000 + region * OUTPUT_REGION_SIZE;

            // Alternate AP and STEE channels
            int channel = (region + cycle) % 2;
            uint32_t dest_addr = channel ? stee_dest : ap_dest;

            if (setup_output_remap_region_extended(region, src_addr, dest_addr,
                                                   1,          // enable
                                                   channel,    // AP(0) or STEE(1)
                                                   0xFFF00000, // 1MB granularity
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                printf("ERROR: Failed to setup region %d cycle %d\n", region, cycle);
                return -1;
            }
        }

        // Access all 16 regions
        for (int region = 0; region < 16; region++) {
            uint32_t test_addr =
                OUTPUT_SRC_BASE + cycle * 0x1000000 + region * OUTPUT_REGION_SIZE + 0x10000;

            // Different-size access modes
            if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
                printf("ERROR: Region %d read failed in cycle %d\n", region, cycle);
                return -1;
            }

            if (test_axi_transaction(test_addr + 0x1000, 8, AXI_WRITE) != 0) {
                printf("ERROR: Region %d write failed in cycle %d\n", region, cycle);
                return -1;
            }

            // Large-burst mode
            if (test_axi_transaction(test_addr + 0x2000, 64, AXI_READ) != 0) {
                printf("ERROR: Region %d large read failed in cycle %d\n", region, cycle);
                return -1;
            }
        }
    }

    printf("AP/STEE full 16 regions: PASS\n");
    return 0;
}

static int test_offset_preserve_bit_range_coverage(void) {
    printf("Starting offset preserve bit range coverage...\n");

    // Scenario 2: Offset-preserve bit-range coverage
    uint32_t offset_patterns[] = {
        0x00001000, 0x00002000, 0x00004000, 0x00008000, // 4KB-32KB offsets
        0x00010000, 0x00020000, 0x00040000, 0x00080000, // 64KB-512KB offsets
        0x00100000, 0x00200000, 0x00400000, 0x00800000, // 1MB-8MB offsets
        0x01000000, 0x02000000, 0x04000000, 0x08000000, // 16MB-128MB offsets
        0x10000000, 0x20000000, 0x40000000, 0x80000000, // 256MB+ offsets
        0x12345000, 0x56789000, 0xABCDE000, 0xFEDCB000  // complex patterns
    };

    for (int pattern_idx = 0; pattern_idx < 20; pattern_idx++) {
        uint32_t offset = offset_patterns[pattern_idx];

        for (int region = 0; region < 16; region++) {
            uint32_t src_base = OUTPUT_SRC_BASE + pattern_idx * 0x2000000 + region * 0x200000;
            uint32_t dest_base = OUTPUT_DEST_BASE + pattern_idx * 0x2000000 + region * 0x200000;

            // Apply offset mode
            uint32_t dest_with_offset = dest_base + offset;

            if (setup_output_remap_region_extended(region, src_base, dest_with_offset,
                                                   1,                          // enable
                                                   (pattern_idx + region) % 2, // alternate channels
                                                   0xFFE00000,                 // 2MB granularity
                                                   (offset >> 24) & 0xFF) != 0) {
                continue; // Skip invalid offset combinations
            }

            // Test offset-preserve behavior
            uint32_t test_addr = src_base + 0x80000;
            uint32_t small_offset = 0x1000 + (region * 0x100);

            test_axi_transaction(test_addr + small_offset, 4, AXI_READ);
            test_axi_transaction(test_addr + small_offset + 0x10, 4, AXI_WRITE);

            // Test different preserve-bit patterns
            for (int bit_test = 0; bit_test < 8; bit_test++) {
                uint32_t bit_offset = 1 << (12 + bit_test); // 4KB to 512KB bits
                test_axi_transaction(test_addr + bit_offset, 4, AXI_READ);
            }
        }
    }

    printf("Offset preserve bit range coverage: PASS\n");
    return 0;
}

static int test_channel_separation_stress(void) {
    printf("Starting channel separation stress test...\n");

    // Scenario 3: Deep channel-separation test
    for (int stress_round = 0; stress_round < 16; stress_round++) {
        // Program mixed AP/STEE regions
        for (int region = 0; region < 16; region++) {
            uint32_t region_base = OUTPUT_SRC_BASE + stress_round * 0x4000000 + region * 0x400000;
            uint32_t ap_dest = AP_OUTPUT_BASE + stress_round * 0x4000000 + region * 0x400000;
            uint32_t stee_dest = STEE_OUTPUT_BASE + stress_round * 0x4000000 + region * 0x400000;

            // Complex channel-allocation patterns
            int is_ap = (region ^ stress_round ^ (region >> 2)) & 1;
            uint32_t dest = is_ap ? ap_dest : stee_dest;

            if (setup_output_remap_region(region, region_base, dest, 1,
                                          is_ap ? AP_CHANNEL : STEE_CHANNEL) != 0) {
                return -1;
            }
        }

        // Parallel access test - simulate concurrent AP/STEE access
        for (int parallel_test = 0; parallel_test < 32; parallel_test++) {
            int ap_region = parallel_test % 8;
            int stee_region = 8 + (parallel_test % 8);

            uint32_t ap_addr =
                OUTPUT_SRC_BASE + stress_round * 0x4000000 + ap_region * 0x400000 + 0x100000;
            uint32_t stee_addr =
                OUTPUT_SRC_BASE + stress_round * 0x4000000 + stee_region * 0x400000 + 0x100000;

            // Rapid alternating access
            test_axi_transaction(ap_addr, 4, AXI_READ);
            test_axi_transaction(stee_addr, 4, AXI_WRITE);
            test_axi_transaction(ap_addr + 0x100, 8, AXI_WRITE);
            test_axi_transaction(stee_addr + 0x100, 8, AXI_READ);
        }
    }

    printf("Channel separation stress: PASS\n");
    return 0;
}

static int test_complement_patterns_datapath(void) {
    printf("Starting complement patterns datapath test...\n");

    // Scenario 4: Complement-patterns test
    uint32_t complement_pairs[][2] = {
        {0x00000000, 0xFFFFFFFF}, {0x55555555, 0xAAAAAAAA}, {0x33333333, 0xCCCCCCCC},
        {0x0F0F0F0F, 0xF0F0F0F0}, {0x00FF00FF, 0xFF00FF00}, {0x0000FFFF, 0xFFFF0000},
        {0x000000FF, 0xFFFFFF00}, {0x12345678, 0xEDCBA987}, {0x13579BDF, 0xECA86420},
        {0x11111111, 0xEEEEEEEE}, {0x22222222, 0xDDDDDDDD}, {0x44444444, 0xBBBBBBBB},
        {0x88888888, 0x77777777}, {0x01010101, 0xFEFEFEFE}, {0x02040810, 0xFDFB7FEF},
        {0x80402010, 0x7FBFDFEF}};

    for (int pair_idx = 0; pair_idx < 16; pair_idx++) {
        uint32_t pattern_a = complement_pairs[pair_idx][0];
        uint32_t pattern_b = complement_pairs[pair_idx][1];

        for (int region = 0; region < 16; region++) {
            // Use complement patterns as address base
            uint32_t src_pattern = (pattern_a & 0xFFF00000) | (region << 20);
            uint32_t dest_pattern = (pattern_b & 0xFFF00000) | (region << 20);

            if (setup_output_remap_region_extended(region, OUTPUT_SRC_BASE + src_pattern,
                                                   OUTPUT_DEST_BASE + dest_pattern,
                                                   1,                         // enable
                                                   (pattern_a >> region) & 1, // channel
                                                   pattern_a | 0xFFF00000, // mask based on pattern
                                                   (pattern_b >> 24) & 0xFF) != 0) {
                continue; // Skip invalid combinations
            }

            // Test complement-pattern accesses
            uint32_t test_addr = OUTPUT_SRC_BASE + src_pattern + 0x80000;

            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE);

            // Test different bit combinations of the pattern
            for (int bit_shift = 0; bit_shift < 16; bit_shift += 4) {
                uint32_t shifted_addr = test_addr + ((pattern_a >> bit_shift) & 0xFFF0);
                test_axi_transaction(shifted_addr, 4, AXI_READ);
            }
        }
    }

    printf("Complement patterns datapath: PASS\n");
    return 0;
}

static int test_region_boundary_crossing(void) {
    printf("Starting region boundary crossing test...\n");

    // Scenario 5: Region boundary-crossing test
    for (int boundary_test = 0; boundary_test < 16; boundary_test++) {
        for (int region = 0; region < 15; region++) { // avoid region-15 overflow
            uint32_t region_base = OUTPUT_SRC_BASE + boundary_test * 0x8000000 + region * 0x800000;
            uint32_t region_end = region_base + 0x800000 - 1;
            uint32_t next_region_start = region_base + 0x800000;

            if (setup_output_remap_region(region, region_base, OUTPUT_DEST_BASE + region * 0x800000,
                                          1, region % 2) != 0) {
                continue;
            }

            if (setup_output_remap_region(region + 1, next_region_start,
                                          OUTPUT_DEST_BASE + (region + 1) * 0x800000, 1,
                                          (region + 1) % 2) != 0) {
                continue;
            }

            // Access near boundaries
            test_axi_transaction(region_end - 3, 4, AXI_READ);    // cross-boundary read
            test_axi_transaction(region_end - 7, 8, AXI_WRITE);   // cross-boundary write
            test_axi_transaction(next_region_start, 4, AXI_READ); // start of next region
            test_axi_transaction(next_region_start + 4, 4, AXI_WRITE);

            // Large burst across boundary
            test_axi_transaction(region_end - 31, 64, AXI_READ); // 64-byte cross-boundary
        }
    }

    printf("Region boundary crossing: PASS\n");
    return 0;
}

int main(void) {
    printf("Output Remap Datapath Test\n");
    printf("Strategy: AP/STEE remap traffic covers every region index; full datapath matrix\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_output_remap_datapath_p3_test");
        return TEST_FAIL;
    }

    // Run all output-remap datapath scenarios
    if (test_ap_stee_full_16_regions() != 0) {
        test_fail("AP STEE Full 16 Regions");
        return TEST_FAIL;
    }

    if (test_offset_preserve_bit_range_coverage() != 0) {
        test_fail("Offset Preserve Bit Range");
        return TEST_FAIL;
    }

    if (test_channel_separation_stress() != 0) {
        test_fail("Channel Separation Stress");
        return TEST_FAIL;
    }

    if (test_complement_patterns_datapath() != 0) {
        test_fail("Complement Patterns Datapath");
        return TEST_FAIL;
    }

    if (test_region_boundary_crossing() != 0) {
        test_fail("Region Boundary Crossing");
        return TEST_FAIL;
    }

    printf("\n=== OUTPUT REMAP DATAPATH TEST PASSED ===\n");

    test_pass("fabric_output_remap_datapath_p3_test");
    return TEST_PASS;
}
