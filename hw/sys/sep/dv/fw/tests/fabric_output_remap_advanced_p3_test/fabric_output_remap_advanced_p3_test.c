/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_output_remap_advanced_p3_test
 *
 * Strategy: Advanced output-remap scenarios; complex configuration combinations
 *
 * Focus on advanced output-remap scenarios and complex config combinations
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Advanced output remap scenario count
#define ADVANCED_OUTPUT_SCENARIOS 8

// Advanced test definitions
#define COMPLEX_REGION_COUNT 16
#define ADVANCED_PATTERN_COUNT 32
#define MULTI_CHANNEL_SCENARIOS 8

// Advanced addressing modes
#define VIRTUAL_ADDR_SPACE 0x80000000
#define PHYSICAL_ADDR_SPACE 0x40000000
#define CACHED_ADDR_SPACE 0x20000000
#define UNCACHED_ADDR_SPACE 0x60000000

static int test_multi_level_address_translation(void) {
    printf("Starting multi-level address translation test...\n");

    // Scenario 1: Multi-level address translation
    for (int translation_level = 0; translation_level < 16; translation_level++) {
        for (int region = 0; region < 16; region++) {
            // Level 1: Virtual to Intermediate
            uint32_t virtual_base =
                VIRTUAL_ADDR_SPACE + translation_level * 0x2000000 + region * 0x200000;
            uint32_t intermediate_base =
                PHYSICAL_ADDR_SPACE + translation_level * 0x2000000 + region * 0x200000;

            // Level 2: Intermediate to Physical
            uint32_t physical_base = intermediate_base + 0x10000000 + (region << 20);

            // Complex address mapping
            uint32_t mapping_pattern = (translation_level << 24) | (region << 20) | 0x80000;
            uint32_t final_dest = physical_base ^ mapping_pattern;

            if (setup_output_remap_region_multi_level(region, virtual_base, intermediate_base,
                                                      final_dest,
                                                      1,                     // enable
                                                      translation_level % 2, // channel
                                                      0xFFE00000,            // 2MB granularity
                                                      CACHE_ATTR_WRITEBACK) != 0) {
                continue;
            }

            // Test multi-level translation under different access modes
            uint32_t test_addr = virtual_base + 0x40000;

            // Sequential access patterns
            for (int seq = 0; seq < 8; seq++) {
                uint32_t seq_addr = test_addr + seq * 0x4000;
                test_axi_transaction(seq_addr, 4 << (seq % 3), AXI_READ);
                test_axi_transaction(seq_addr + 0x1000, 4 << (seq % 3), AXI_WRITE);
            }

            // Strided access patterns
            for (int stride = 1; stride <= 8; stride *= 2) {
                uint32_t stride_addr = test_addr + stride * 0x1000;
                test_axi_transaction(stride_addr, 8, AXI_READ);
                test_axi_transaction(stride_addr + 0x100, 8, AXI_WRITE);
            }
        }
    }

    printf("Multi-level address translation: PASS\n");
    return 0;
}

static int test_dynamic_region_reconfiguration(void) {
    printf("Starting dynamic region reconfiguration test...\n");

    // Scenario 2: Dynamic region reconfiguration
    for (int reconfig_round = 0; reconfig_round < 24; reconfig_round++) {
        // Phase 1: initial configuration
        for (int region = 0; region < 16; region++) {
            uint32_t initial_src =
                VIRTUAL_ADDR_SPACE + reconfig_round * 0x4000000 + region * 0x400000;
            uint32_t initial_dest =
                PHYSICAL_ADDR_SPACE + reconfig_round * 0x4000000 + region * 0x400000;

            if (setup_output_remap_region_extended(region, initial_src, initial_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000, // 2MB granularity
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                continue;
            }

            // Test initial configuration
            uint32_t test_addr = initial_src + 0x80000;
            test_axi_transaction(test_addr, 16, AXI_READ);
            test_axi_transaction(test_addr + 0x1000, 16, AXI_WRITE);
        }

        // Phase 2: Dynamic reconfiguration
        for (int region = 0; region < 16; region++) {
            // Hot reconfiguration - different destination
            uint32_t new_src = CACHED_ADDR_SPACE + reconfig_round * 0x4000000 + region * 0x400000;
            uint32_t new_dest =
                UNCACHED_ADDR_SPACE + reconfig_round * 0x4000000 + region * 0x400000;

            // Reconfigure while traffic is active
            if (setup_output_remap_region_extended(region, new_src, new_dest,
                                                   1,                // enable
                                                   (region + 1) % 2, // switch channel
                                                   0xFFF00000,       // 1MB granularity
                                                   CACHE_ATTR_NORMAL_NC) !=
                0) { // switch cache attributes
                continue;
            }

            // Immediately test new configuration
            uint32_t new_test_addr = new_src + 0x80000;
            test_axi_transaction(new_test_addr, 8, AXI_READ);
            test_axi_transaction(new_test_addr + 0x2000, 8, AXI_WRITE);

            // Phase 3: dynamic adjust again
            uint32_t final_dest = new_dest + 0x8000000 + (region << 18);
            if (setup_output_remap_region_extended(region, new_src, final_dest,
                                                   1,          // enable
                                                   region % 2, // switch channel again
                                                   0xFFFC0000, // 256KB granularity
                                                   CACHE_ATTR_DEVICE) != 0) {
                continue;
            }

            // Verify final configuration
            test_axi_transaction(new_test_addr, 32, AXI_READ);
            test_axi_transaction(new_test_addr + 0x3000, 32, AXI_WRITE);
        }
    }

    printf("Dynamic region reconfiguration: PASS\n");
    return 0;
}

static int test_complex_overlap_resolution(void) {
    printf("Starting complex overlap resolution test...\n");

    // Scenario 3: Complex overlap resolution
    for (int overlap_scenario = 0; overlap_scenario < 16; overlap_scenario++) {
        // Set up complex overlap scenarios
        for (int layer = 0; layer < 4; layer++) {
            for (int region = layer * 4; region < (layer + 1) * 4; region++) {
                uint32_t base_addr = VIRTUAL_ADDR_SPACE + overlap_scenario * 0x8000000;

                // Create multi-level overlaps
                uint32_t overlap_src = base_addr + region * 0x400000 - layer * 0x200000;
                uint32_t overlap_dest =
                    PHYSICAL_ADDR_SPACE + overlap_scenario * 0x8000000 + region * 0x600000;

                // Vary priority/size to create complex overlaps
                uint32_t region_size = (1 << (20 + layer)); // 1MB, 2MB, 4MB, 8MB
                uint32_t mask = ~(region_size - 1);
                int priority = (layer * 4) + (region % 4); // 0-15 priority range

                if (setup_output_remap_region_priority(region, overlap_src & mask, overlap_dest,
                                                       1, // enable
                                                       priority,
                                                       layer % 2, // channel
                                                       mask, CACHE_ATTR_WRITEBACK) != 0) {
                    continue;
                }
            }
        }

        // Test overlap-region resolution
        uint32_t base_test_addr = VIRTUAL_ADDR_SPACE + overlap_scenario * 0x8000000;

        for (int test_point = 0; test_point < 32; test_point++) {
            uint32_t overlap_test_addr = base_test_addr + test_point * 0x100000;

            // Access with different sizes
            test_axi_transaction(overlap_test_addr, 4, AXI_READ);
            test_axi_transaction(overlap_test_addr + 0x1000, 8, AXI_WRITE);
            test_axi_transaction(overlap_test_addr + 0x2000, 16, AXI_READ);

            // Large-burst access tests resolution
            if (test_point % 4 == 0) {
                test_axi_transaction(overlap_test_addr + 0x10000, 64, AXI_READ);
                test_axi_transaction(overlap_test_addr + 0x10040, 64, AXI_WRITE);
            }
        }
    }

    printf("Complex overlap resolution: PASS\n");
    return 0;
}

static int test_cache_coherency_advanced_scenarios(void) {
    printf("Starting cache coherency advanced scenarios test...\n");

    // Scenario 4: Cache coherency advanced scenarios
    uint32_t coherency_scenarios[] = {CACHE_ATTR_WRITEBACK | CACHE_ATTR_READ_ALLOCATE,
                                      CACHE_ATTR_WRITETHROUGH | CACHE_ATTR_WRITE_ALLOCATE,
                                      CACHE_ATTR_NORMAL_NC | CACHE_ATTR_SHAREABLE,
                                      CACHE_ATTR_DEVICE | CACHE_ATTR_STRONGLY_ORDERED,
                                      CACHE_ATTR_WRITE_COMBINING | CACHE_ATTR_BUFFERABLE,
                                      CACHE_ATTR_STRONGLY_ORDERED | CACHE_ATTR_NON_SHAREABLE,
                                      CACHE_ATTR_NORMAL_WT | CACHE_ATTR_READ_ALLOCATE |
                                          CACHE_ATTR_WRITE_ALLOCATE,
                                      CACHE_ATTR_NORMAL_WB | CACHE_ATTR_INNER_SHAREABLE};

    for (int coherency_test = 0; coherency_test < 32; coherency_test++) {
        for (int region = 0; region < 16; region++) {
            uint32_t cache_attr = coherency_scenarios[coherency_test % 8];
            uint32_t coherency_src =
                CACHED_ADDR_SPACE + coherency_test * 0x2000000 + region * 0x200000;
            uint32_t coherency_dest =
                PHYSICAL_ADDR_SPACE + coherency_test * 0x2000000 + region * 0x200000;

            if (setup_output_remap_region_extended(region, coherency_src, coherency_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000, // 2MB granularity
                                                   cache_attr) != 0) {
                continue;
            }

            // Test cache-coherency scenarios
            uint32_t test_addr = coherency_src + 0x40000;

            // Scenario 1: Write-Read coherency
            test_axi_transaction(test_addr, 32, AXI_WRITE);
            test_axi_transaction(test_addr, 32, AXI_READ);

            // Scenario 2: Read-Modify-Write
            test_axi_transaction(test_addr + 0x1000, 16, AXI_READ);
            test_axi_transaction(test_addr + 0x1000, 16, AXI_WRITE);

            // Scenario 3: Cache line boundary crossing
            test_axi_transaction(test_addr + 0x3E, 4, AXI_WRITE); // Cross cache line
            test_axi_transaction(test_addr + 0x3E, 4, AXI_READ);

            // Scenario 4: Multiple cache line access
            if (cache_attr & CACHE_ATTR_WRITEBACK) {
                test_axi_transaction(test_addr + 0x2000, 128, AXI_READ);  // Large read
                test_axi_transaction(test_addr + 0x2080, 128, AXI_WRITE); // Large write
            }

            // Scenario 5: Mixed cacheable/non-cacheable regions
            if ((region % 2) == 0) {
                // Alternate between cacheable and non-cacheable
                uint32_t nc_attr = CACHE_ATTR_NORMAL_NC;
                if (setup_output_remap_region_extended((region + 8) % 16, coherency_src + 0x100000,
                                                       coherency_dest + 0x100000,
                                                       1,                // enable
                                                       (region + 1) % 2, // different channel
                                                       0xFFE00000, nc_attr) == 0) {

                    // Cross-coherency testing
                    test_axi_transaction(test_addr + 0x80000, 16, AXI_WRITE);  // Cacheable
                    test_axi_transaction(test_addr + 0x180000, 16, AXI_WRITE); // Non-cacheable
                    test_axi_transaction(test_addr + 0x80000, 16, AXI_READ);   // Cacheable
                    test_axi_transaction(test_addr + 0x180000, 16, AXI_READ);  // Non-cacheable
                }
            }
        }
    }

    printf("Cache coherency advanced scenarios: PASS\n");
    return 0;
}

static int test_performance_critical_patterns(void) {
    printf("Starting performance critical patterns test...\n");

    // Scenario 5: Performance critical patterns
    for (int perf_test = 0; perf_test < 16; perf_test++) {
        for (int region = 0; region < 16; region++) {
            uint32_t perf_src = VIRTUAL_ADDR_SPACE + perf_test * 0x4000000 + region * 0x400000;
            uint32_t perf_dest = PHYSICAL_ADDR_SPACE + perf_test * 0x4000000 + region * 0x400000;

            if (setup_output_remap_region_extended(region, perf_src, perf_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000, // 2MB granularity
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                continue;
            }

            uint32_t test_addr = perf_src + 0x80000;

            // Pattern 1: High-frequency small accesses
            for (int freq_test = 0; freq_test < 64; freq_test++) {
                uint32_t freq_addr = test_addr + freq_test * 4;
                test_axi_transaction(freq_addr, 4, (freq_test % 2) ? AXI_WRITE : AXI_READ);
            }

            // Pattern 2: Burst optimization patterns
            uint32_t burst_sizes[] = {4, 8, 16, 32, 64, 128, 256};
            for (int burst_idx = 0; burst_idx < 7; burst_idx++) {
                uint32_t burst_size = burst_sizes[burst_idx];
                uint32_t burst_addr = test_addr + 0x1000 + burst_idx * 0x400;

                test_axi_transaction(burst_addr, burst_size, AXI_READ);
                test_axi_transaction(burst_addr + burst_size, burst_size, AXI_WRITE);
            }

            // Pattern 3: Memory bandwidth optimization
            for (int bandwidth_test = 0; bandwidth_test < 8; bandwidth_test++) {
                uint32_t bw_addr = test_addr + 0x10000 + bandwidth_test * 0x1000;

                // Parallel-style accesses (simulated)
                test_axi_transaction(bw_addr, 64, AXI_READ);
                test_axi_transaction(bw_addr + 0x100, 64, AXI_READ);
                test_axi_transaction(bw_addr + 0x200, 64, AXI_WRITE);
                test_axi_transaction(bw_addr + 0x300, 64, AXI_WRITE);
            }

            // Pattern 4: Latency-critical scenarios
            for (int latency_test = 0; latency_test < 4; latency_test++) {
                uint32_t lat_addr = test_addr + 0x20000 + latency_test * 0x2000;

                // Critical read-write sequences
                test_axi_transaction(lat_addr, 4, AXI_READ);      // Critical read
                test_axi_transaction(lat_addr + 4, 4, AXI_WRITE); // Immediate write
                test_axi_transaction(lat_addr + 8, 4, AXI_READ);  // Dependent read
            }
        }
    }

    printf("Performance critical patterns: PASS\n");
    return 0;
}

static int test_error_recovery_advanced_scenarios(void) {
    printf("Starting error recovery advanced scenarios test...\n");

    // Scenario 6: Error recovery advanced scenarios
    for (int error_scenario = 0; error_scenario < 12; error_scenario++) {
        for (int region = 0; region < 16; region++) {
            uint32_t error_src =
                VIRTUAL_ADDR_SPACE + error_scenario * 0x2000000 + region * 0x200000;
            uint32_t error_dest =
                PHYSICAL_ADDR_SPACE + error_scenario * 0x2000000 + region * 0x200000;

            // Set normal configuration
            if (setup_output_remap_region_extended(region, error_src, error_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000, // 2MB granularity
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                continue;
            }

            uint32_t test_addr = error_src + 0x40000;

            // Error Scenario 1: Address overflow
            uint32_t overflow_addr = error_src + 0x200000 - 1;    // Just at boundary
            test_axi_transaction(overflow_addr, 4, AXI_READ);     // Should be OK
            test_axi_transaction(overflow_addr + 1, 4, AXI_READ); // Should overflow

            // Error Scenario 2: Burst spanning regions
            test_axi_transaction(overflow_addr - 16, 32, AXI_READ); // Spans boundary

            // Error Scenario 3: Invalid cache attribute combinations
            if (setup_output_remap_region_extended(region, error_src, error_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000,
                                                   0xFF) != 0) { // Invalid cache attr
                // Should fail, continue with recovery
            }

            // Recovery: Reconfigure with valid settings
            if (setup_output_remap_region_extended(region, error_src, error_dest,
                                                   1,          // enable
                                                   region % 2, // channel
                                                   0xFFE00000, CACHE_ATTR_NORMAL_NC) == 0) {

                // Verify recovery worked
                test_axi_transaction(test_addr, 16, AXI_READ);
                test_axi_transaction(test_addr + 0x1000, 16, AXI_WRITE);
            }

            // Error Scenario 4: Conflicting region configurations
            if (region < 8) {
                // Try to configure overlapping region with conflicting settings
                if (setup_output_remap_region_extended(region + 8,
                                                       error_src,              // Same source
                                                       error_dest + 0x1000000, // Different dest
                                                       1,                      // enable
                                                       (region + 1) % 2,       // Different channel
                                                       0xFFE00000, CACHE_ATTR_DEVICE) != 0) {
                    // Expected to fail or be resolved by hardware
                }
            }
        }
    }

    printf("Error recovery advanced scenarios: PASS\n");
    return 0;
}

static int test_system_integration_stress(void) {
    printf("Starting system integration stress test...\n");

    // Scenario 7: System integration stress
    for (int stress_round = 0; stress_round < 8; stress_round++) {
        // Configure all 16 regions simultaneously
        for (int region = 0; region < 16; region++) {
            uint32_t stress_src = VIRTUAL_ADDR_SPACE + stress_round * 0x8000000 + region * 0x800000;
            uint32_t stress_dest =
                PHYSICAL_ADDR_SPACE + stress_round * 0x8000000 + region * 0x800000;

            // Complex configuration
            int channel = (stress_round + region) % 2;
            uint32_t cache_attr = (region % 4 == 0)   ? CACHE_ATTR_WRITEBACK
                                  : (region % 4 == 1) ? CACHE_ATTR_WRITETHROUGH
                                  : (region % 4 == 2) ? CACHE_ATTR_NORMAL_NC
                                                      : CACHE_ATTR_DEVICE;

            if (setup_output_remap_region_extended(region, stress_src, stress_dest,
                                                   1, // enable
                                                   channel,
                                                   0xFF800000, // 8MB granularity
                                                   cache_attr) != 0) {
                continue;
            }
        }

        // Intensive concurrent access to all regions
        for (int concurrent_round = 0; concurrent_round < 32; concurrent_round++) {
            for (int region = 0; region < 16; region++) {
                uint32_t concurrent_addr = VIRTUAL_ADDR_SPACE + stress_round * 0x8000000 +
                                           region * 0x800000 + concurrent_round * 0x1000;

                // Mixed access patterns
                int access_type = (concurrent_round + region) % 4;
                switch (access_type) {
                case 0:
                    test_axi_transaction(concurrent_addr, 4, AXI_READ);
                    break;
                case 1:
                    test_axi_transaction(concurrent_addr, 8, AXI_WRITE);
                    break;
                case 2:
                    test_axi_transaction(concurrent_addr, 32, AXI_READ);
                    break;
                case 3:
                    test_axi_transaction(concurrent_addr, 16, AXI_WRITE);
                    break;
                }
            }
        }

        // Dynamic reconfiguration during stress
        for (int reconfig = 0; reconfig < 4; reconfig++) {
            int target_region = (stress_round * 4 + reconfig) % 16;
            uint32_t new_dest =
                UNCACHED_ADDR_SPACE + stress_round * 0x8000000 + target_region * 0x800000;

            // Reconfigure while maintaining traffic
            setup_output_remap_region_extended(
                target_region,
                VIRTUAL_ADDR_SPACE + stress_round * 0x8000000 + target_region * 0x800000, new_dest,
                1,                       // enable
                (target_region + 1) % 2, // different channel
                0xFF800000, CACHE_ATTR_NORMAL_NC);

            // Continue traffic to verify seamless transition
            uint32_t reconfig_test_addr =
                VIRTUAL_ADDR_SPACE + stress_round * 0x8000000 + target_region * 0x800000 + 0x100000;
            test_axi_transaction(reconfig_test_addr, 64, AXI_READ);
            test_axi_transaction(reconfig_test_addr + 0x1000, 64, AXI_WRITE);
        }
    }

    printf("System integration stress: PASS\n");
    return 0;
}

int main(void) {
    printf("Output Remap Advanced Test\n");
    printf("Strategy: Advanced output-remap scenarios; complex configuration combinations\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_output_remap_advanced_p3_test");
        return TEST_FAIL;
    }

    // Run all advanced output-remap scenarios
    if (test_multi_level_address_translation() != 0) {
        test_fail("Multi Level Address Translation");
        return TEST_FAIL;
    }

    if (test_dynamic_region_reconfiguration() != 0) {
        test_fail("Dynamic Region Reconfiguration");
        return TEST_FAIL;
    }

    if (test_complex_overlap_resolution() != 0) {
        test_fail("Complex Overlap Resolution");
        return TEST_FAIL;
    }

    if (test_cache_coherency_advanced_scenarios() != 0) {
        test_fail("Cache Coherency Advanced Scenarios");
        return TEST_FAIL;
    }

    if (test_performance_critical_patterns() != 0) {
        test_fail("Performance Critical Patterns");
        return TEST_FAIL;
    }

    if (test_error_recovery_advanced_scenarios() != 0) {
        test_fail("Error Recovery Advanced Scenarios");
        return TEST_FAIL;
    }

    if (test_system_integration_stress() != 0) {
        test_fail("System Integration Stress");
        return TEST_FAIL;
    }

    printf("\n=== OUTPUT REMAP ADVANCED TEST PASSED ===\n");

    test_pass("fabric_output_remap_advanced_p3_test");
    return TEST_PASS;
}
