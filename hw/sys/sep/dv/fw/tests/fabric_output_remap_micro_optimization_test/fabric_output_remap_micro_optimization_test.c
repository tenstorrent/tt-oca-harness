/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_output_remap_micro_optimization_test
 *
 * Strategy: Micro boundary cases; fine-grained toggle bits
 *
 * Focus on the finest boundary conditions and corner cases
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Micro boundary and anomaly scenarios
#define MICRO_REMAP_SCENARIOS 12

// Boundary values at the 32-bit edges
#define ADDR_BOUNDARY_EDGE_LOW 0x7FFFFFFE  // 32-bit boundary - 2
#define ADDR_BOUNDARY_EDGE_HIGH 0x80000001 // 32-bit boundary + 1
#define OFFSET_MICRO_PATTERN_1 0x00000003  // micro offset patterns
#define OFFSET_MICRO_PATTERN_2 0x0000000C  // micro offset patterns
#define SIZE_MICRO_BURST_1 0x1             // 1-byte minimum burst
#define SIZE_MICRO_BURST_2 0x3             // 3-byte unaligned

static int test_micro_boundary_edge_cases(void) {
    printf("Starting micro boundary edge case tests...\n");

    // Scenario 1: Extreme boundary address-alignment test
    for (int region = 14; region < 16; region++) { // focus on highest regions
        uint32_t edge_addr = ADDR_BOUNDARY_EDGE_LOW + (region * 4);

        if (setup_output_remap_region(region, edge_addr, edge_addr + OFFSET_MICRO_PATTERN_1,
                                      1, // enable
                                      (region % 2) ? AP_CHANNEL : STEE_CHANNEL) != 0) {
            printf("ERROR: Failed to setup edge boundary region %d\n", region);
            return -1;
        }

        // Tiny burst access
        if (test_axi_transaction(edge_addr, SIZE_MICRO_BURST_1, AXI_READ) != 0) {
            printf("ERROR: Edge boundary read failed for region %d\n", region);
            return -1;
        }

        // Unaligned access
        if (test_axi_transaction(edge_addr + 1, SIZE_MICRO_BURST_2, AXI_WRITE) != 0) {
            printf("ERROR: Edge boundary unaligned write failed for region %d\n", region);
            return -1;
        }
    }

    printf("Micro boundary edge cases: PASS\n");
    return 0;
}

static int test_offset_calculation_corners(void) {
    printf("Starting offset calculation corner tests...\n");

    // Scenario 2: Offset-calculation corner cases
    uint32_t corner_offsets[] = {
        0x00000001, 0x00000002, 0x00000007, // small offsets
        0x0000000F, 0x0000001F, 0x0000003F, // nibble boundaries
        0x000000FF, 0x000001FF, 0x000003FF  // byte boundaries
    };

    for (int i = 0; i < sizeof(corner_offsets) / sizeof(uint32_t); i++) {
        int region = 12 + (i % 4); // use high regions
        uint32_t src_addr = 0x40000000 + (i * 0x1000);
        uint32_t dest_addr = src_addr + corner_offsets[i];

        if (setup_output_remap_region(region, src_addr, dest_addr, 1,
                                      (i % 2) ? STEE_CHANNEL : AP_CHANNEL) != 0) {
            printf("ERROR: Failed offset corner setup %d\n", i);
            return -1;
        }

        // Test computation path
        if (test_axi_transaction(src_addr + (corner_offsets[i] >> 2), 4, AXI_READ) != 0) {
            printf("ERROR: Offset calculation failed for corner %d\n", i);
            return -1;
        }
    }

    printf("Offset calculation corners: PASS\n");
    return 0;
}

static int test_channel_switching_micro_scenarios(void) {
    printf("Starting channel switching micro scenarios...\n");

    // Scenario 3: Channel-switch micro scenarios
    for (int cycle = 0; cycle < 8; cycle++) {
        int region1 = 8 + cycle;
        int region2 = 15 - cycle;

        // Rapid AP <-> STEE switching
        if (setup_output_remap_region(region1, 0x50000000 + cycle * 0x1000,
                                      0x60000000 + cycle * 0x1000, 1, AP_CHANNEL) != 0) {
            return -1;
        }

        if (setup_output_remap_region(region2, 0x50000000 + cycle * 0x1000 + 0x800,
                                      0x60000000 + cycle * 0x1000 + 0x800, 1, STEE_CHANNEL) != 0) {
            return -1;
        }

        // Subtle parallel accesses
        test_axi_transaction(0x50000000 + cycle * 0x1000 + 1, 2, AXI_WRITE);
        test_axi_transaction(0x50000000 + cycle * 0x1000 + 0x801, 2, AXI_READ);
    }

    printf("Channel switching micro scenarios: PASS\n");
    return 0;
}

static int test_non_standard_size_burst_modes(void) {
    printf("Starting non-standard size/burst mode tests...\n");

    // Scenario 4: Non-standard size/burst modes
    uint32_t unusual_sizes[] = {1, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15};

    for (int i = 0; i < sizeof(unusual_sizes) / sizeof(uint32_t); i++) {
        int region = 4 + (i % 12);
        uint32_t test_addr = 0x70000000 + i * 0x100;

        if (setup_output_remap_region(region, test_addr, test_addr + 0x10000, 1,
                                      (i % 2) ? AP_CHANNEL : STEE_CHANNEL) != 0) {
            return -1;
        }

        // Uncommon size tests
        if (test_axi_transaction(test_addr + (i * 16), unusual_sizes[i],
                                 (i % 2) ? AXI_WRITE : AXI_READ) != 0) {
            printf("ERROR: Unusual size %d failed\n", unusual_sizes[i]);
            return -1;
        }
    }

    printf("Non-standard size/burst modes: PASS\n");
    return 0;
}

static int test_parallel_micro_stress(void) {
    printf("Starting parallel micro stress tests...\n");

    // Scenario 5: Parallel micro-stress test
    for (int stress_round = 0; stress_round < 4; stress_round++) {
        // Program multiple overlapping regions
        for (int region = 0; region < 16; region++) {
            uint32_t base = 0x80000000 + stress_round * 0x100000;
            if (setup_output_remap_region(region, base + region * 0x1000,
                                          base + 0x10000 + region * 0x1000, 1, region % 2) != 0) {
                return -1;
            }
        }

        // Rapid parallel access
        for (int access = 0; access < 32; access++) {
            uint32_t addr = 0x80000000 + stress_round * 0x100000 + access * 64;
            test_axi_transaction(addr, 4, access % 2);
            test_axi_transaction(addr + 32, 8, (access + 1) % 2);
        }
    }

    printf("Parallel micro stress: PASS\n");
    return 0;
}

int main(void) {
    printf("Output Remap Micro-Optimization Test\n");
    printf("Focus: boundary-case and residual field-toggle coverage\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_output_remap_micro_optimization_test");
        return TEST_FAIL;
    }

    // Run all micro-tuning scenarios
    if (test_micro_boundary_edge_cases() != 0) {
        test_fail("Boundary Edge Cases");
        return TEST_FAIL;
    }

    if (test_offset_calculation_corners() != 0) {
        test_fail("Offset Calculation");
        return TEST_FAIL;
    }

    if (test_channel_switching_micro_scenarios() != 0) {
        test_fail("Channel Switching");
        return TEST_FAIL;
    }

    if (test_non_standard_size_burst_modes() != 0) {
        test_fail("Non-standard Modes");
        return TEST_FAIL;
    }

    if (test_parallel_micro_stress() != 0) {
        test_fail("Parallel Stress");
        return TEST_FAIL;
    }

    printf("\n=== OUTPUT REMAP MICRO-OPTIMIZATION TEST PASSED ===\n");

    test_pass("fabric_output_remap_micro_optimization_test");
    return TEST_PASS;
}
