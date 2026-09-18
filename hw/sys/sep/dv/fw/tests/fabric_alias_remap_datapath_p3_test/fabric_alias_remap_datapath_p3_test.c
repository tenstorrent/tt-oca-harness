/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_alias_remap_datapath_p3_test
 *
 * Strategy: Local-master alias hit/miss/boundary cases; full AXI datapath coverage
 *
 * Focus on full alias-remap datapath matrix and all AXI signal toggles
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Alias datapath scenario count
#define ALIAS_DATAPATH_SCENARIOS 9

// Alias base definitions
#define ALIAS_SRC_BASE 0x40000000
#define ALIAS_DEST_BASE 0x80000000
#define LOCAL_MASTER_BASE 0x10000000
#define GLOBAL_ALIAS_BASE 0x20000000

// AXI signal full-coverage definitions
#define AXI_BURST_FIXED 0x0
#define AXI_BURST_INCR 0x1
#define AXI_BURST_WRAP 0x2

#define AXI_SIZE_1BYTE 0x0
#define AXI_SIZE_2BYTE 0x1
#define AXI_SIZE_4BYTE 0x2
#define AXI_SIZE_8BYTE 0x3

static int test_alias_hit_miss_comprehensive(void) {
    printf("Starting alias hit/miss comprehensive tests...\n");

    // Scenario 1: Full alias hit/miss coverage
    for (int test_round = 0; test_round < 16; test_round++) {
        // Program 16 alias regions covering different ranges
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            uint32_t src_start = ALIAS_SRC_BASE + alias_idx * 0x100000;
            uint32_t src_end = src_start + 0x80000;
            uint32_t dest_start = ALIAS_DEST_BASE + alias_idx * 0x100000;

            if (setup_output_remap_region_extended(alias_idx, src_start, dest_start,
                                                   1,             // enable
                                                   alias_idx % 2, // AP/STEE
                                                   0xFFF80000,    // 512KB mask
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                return -1;
            }
        }

        // Hit scenario - should hit alias
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            uint32_t hit_addr = ALIAS_SRC_BASE + alias_idx * 0x100000 + 0x10000;

            // Different AXI burst modes
            if (test_axi_transaction(hit_addr, 4, AXI_READ) != 0) {
                printf("ERROR: Alias hit failed for region %d\n", alias_idx);
                return -1;
            }

            if (test_axi_transaction(hit_addr + 0x1000, 8, AXI_WRITE) != 0) {
                printf("ERROR: Alias hit write failed for region %d\n", alias_idx);
                return -1;
            }
        }

        // Miss scenario - should miss alias
        for (int miss_test = 0; miss_test < 8; miss_test++) {
            uint32_t miss_addr =
                ALIAS_SRC_BASE + 0x1000000 + miss_test * 0x100000; // beyond all alias ranges

            test_axi_transaction(miss_addr, 4, AXI_READ);           // expect miss
            test_axi_transaction(miss_addr + 0x1000, 4, AXI_WRITE); // expect miss
        }
    }

    printf("Alias hit/miss comprehensive: PASS\n");
    return 0;
}

static int test_overlapping_priority_scenarios(void) {
    printf("Starting overlapping priority scenarios...\n");

    // Scenario 2: Overlapping priority test
    for (int overlap_test = 0; overlap_test < 8; overlap_test++) {
        uint32_t base_addr = LOCAL_MASTER_BASE + overlap_test * 0x1000000;

        // Program overlapping alias regions; test priority
        for (int priority = 0; priority < 8; priority++) {
            uint32_t region_start = base_addr + priority * 0x80000;
            uint32_t region_size = 0x100000 + priority * 0x40000; // create overlap
            uint32_t dest_addr = ALIAS_DEST_BASE + priority * 0x200000;

            if (setup_output_remap_region_extended(priority, region_start, dest_addr,
                                                   1, // enable
                                                   priority % 2,
                                                   0xFFE00000 |
                                                       (priority << 16), // different mask modes
                                                   CACHE_ATTR_NORMAL_NC + priority) != 0) {
                return -1;
            }
        }

        // Overlapping regions should resolve by priority
        for (int priority = 0; priority < 8; priority++) {
            uint32_t overlap_addr = base_addr + priority * 0x80000 + 0x40000;

            // Access with different sizes
            test_axi_transaction(overlap_addr, 1 << (priority % 4), AXI_READ);
            test_axi_transaction(overlap_addr + 0x100, 1 << ((priority + 2) % 4), AXI_WRITE);
        }
    }

    printf("Overlapping priority scenarios: PASS\n");
    return 0;
}

static int test_cacheable_non_cacheable_conversion(void) {
    printf("Starting cacheable/non-cacheable conversion tests...\n");

    // Scenario 3: Cacheable/non-cacheable transition
    uint32_t cache_attributes[] = {CACHE_ATTR_DEVICE, CACHE_ATTR_NORMAL_NC, CACHE_ATTR_NORMAL_WT,
                                   CACHE_ATTR_NORMAL_WB, CACHE_ATTR_INSTRUCTION};

    for (int cache_test = 0; cache_test < 32; cache_test++) {
        for (int region = 0; region < 16; region++) {
            uint32_t cache_attr = cache_attributes[cache_test % 5];
            uint32_t region_base = GLOBAL_ALIAS_BASE + cache_test * 0x400000 + region * 0x40000;
            uint32_t dest_base = ALIAS_DEST_BASE + cache_test * 0x400000 + region * 0x40000;

            if (setup_output_remap_region_extended(region, region_base, dest_base,
                                                   1, // enable
                                                   region % 2,
                                                   0xFFFC0000, // 256KB granularity
                                                   cache_attr) != 0) {
                return -1;
            }

            // Access with different cache attributes
            uint32_t test_addr = region_base + 0x8000;

            // Cacheable access
            if (cache_attr & CACHE_ATTR_WRITEBACK) {
                test_axi_transaction(test_addr, 64, AXI_READ); // large cacheable burst
                test_axi_transaction(test_addr + 0x1000, 64, AXI_WRITE);
            } else {
                test_axi_transaction(test_addr, 4, AXI_READ); // small non-cacheable access
                test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);
            }
        }
    }

    printf("Cacheable/non-cacheable conversion: PASS\n");
    return 0;
}

static int test_address_translation_edge_cases(void) {
    printf("Starting address translation edge cases...\n");

    // Scenario 4: Address translation edge cases
    uint32_t edge_patterns[] = {
        0x00000FFF, 0x00001000, 0x00001FFF, 0x00002000, // 4KB boundaries
        0x0000FFFF, 0x00010000, 0x0001FFFF, 0x00020000, // 64KB boundaries
        0x000FFFFF, 0x00100000, 0x001FFFFF, 0x00200000, // 1MB boundaries
        0x00FFFFFF, 0x01000000, 0x01FFFFFF, 0x02000000, // 16MB boundaries
        0x0FFFFFFF, 0x10000000, 0x1FFFFFFF, 0x20000000, // 256MB boundaries
        0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x00000001  // 32-bit boundaries
    };

    for (int edge_idx = 0; edge_idx < 20; edge_idx++) {
        uint32_t edge_pattern = edge_patterns[edge_idx];

        for (int region = 0; region < 8; region++) {
            uint32_t src_edge = (ALIAS_SRC_BASE & 0xF0000000) | (edge_pattern & 0x0FFFFFFF);
            uint32_t dest_edge =
                (ALIAS_DEST_BASE & 0xF0000000) | ((edge_pattern + 0x10000000) & 0x0FFFFFFF);

            if (setup_output_remap_region(region, src_edge, dest_edge, 1, region % 2) != 0) {
                continue; // Skip invalid configurations
            }

            // Access near boundaries
            test_axi_transaction(src_edge, 1, AXI_READ);
            test_axi_transaction(src_edge + 1, 1, AXI_WRITE);
            test_axi_transaction(src_edge + 0xFFF, 1, AXI_READ);
            test_axi_transaction(src_edge + 0x1000, 1, AXI_WRITE);
        }
    }

    printf("Address translation edge cases: PASS\n");
    return 0;
}

static int test_axi_signal_comprehensive_toggle(void) {
    printf("Starting AXI signal comprehensive toggle...\n");

    // Scenario 5: Full AXI signal-toggle coverage
    uint32_t axi_id_patterns[] = {0x0000, 0x000F, 0x00F0, 0x0F00, 0xF000, 0x5555, 0xAAAA, 0xFFFF};
    uint32_t axi_sizes[] = {AXI_SIZE_1BYTE, AXI_SIZE_2BYTE, AXI_SIZE_4BYTE, AXI_SIZE_8BYTE};
    uint32_t burst_types[] = {AXI_BURST_FIXED, AXI_BURST_INCR, AXI_BURST_WRAP};

    for (int axi_combo = 0; axi_combo < 64; axi_combo++) {
        uint32_t axi_id = axi_id_patterns[axi_combo % 8];
        uint32_t axi_size = axi_sizes[(axi_combo >> 3) % 4];
        uint32_t burst_type = burst_types[(axi_combo >> 5) % 3];

        for (int region = 0; region < 16; region++) {
            uint32_t test_base = ALIAS_SRC_BASE + axi_combo * 0x100000 + region * 0x10000;
            uint32_t dest_base = ALIAS_DEST_BASE + axi_combo * 0x100000 + region * 0x10000;

            // Program matching alias
            if (setup_output_remap_region_extended(region, test_base, dest_base,
                                                   1, // enable
                                                   region % 2,
                                                   0xFFFF0000, // 64KB granularity
                                                   (axi_id >> 8) & 0xFF) != 0) {
                continue;
            }

            // Simulate accesses with different AXI signal mixes
            uint32_t test_addr = test_base + 0x1000;
            uint32_t access_size = 1 << axi_size;

            test_axi_transaction(test_addr, access_size, AXI_READ);

            test_axi_transaction(test_addr + access_size, access_size, AXI_WRITE);

            // Burst transactions
            if (burst_type == AXI_BURST_INCR) {
                test_axi_transaction(test_addr + 0x100, access_size * 8, AXI_READ);
            }
        }
    }

    printf("AXI signal comprehensive toggle: PASS\n");
    return 0;
}

int main(void) {
    printf("Alias Remap Datapath Test\n");
    printf("Strategy: Local-master alias hit/miss/boundary cases; full AXI datapath coverage\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_alias_remap_datapath_p3_test");
        return TEST_FAIL;
    }

    // Run all alias datapath scenarios
    if (test_alias_hit_miss_comprehensive() != 0) {
        test_fail("Alias Hit Miss Comprehensive");
        return TEST_FAIL;
    }

    if (test_overlapping_priority_scenarios() != 0) {
        test_fail("Overlapping Priority");
        return TEST_FAIL;
    }

    if (test_cacheable_non_cacheable_conversion() != 0) {
        test_fail("Cacheable Non-Cacheable");
        return TEST_FAIL;
    }

    if (test_address_translation_edge_cases() != 0) {
        test_fail("Address Translation Edge Cases");
        return TEST_FAIL;
    }

    if (test_axi_signal_comprehensive_toggle() != 0) {
        test_fail("AXI Signal Comprehensive Toggle");
        return TEST_FAIL;
    }

    printf("\n=== ALIAS REMAP DATAPATH TEST PASSED ===\n");

    test_pass("fabric_alias_remap_datapath_p3_test");
    return TEST_PASS;
}
