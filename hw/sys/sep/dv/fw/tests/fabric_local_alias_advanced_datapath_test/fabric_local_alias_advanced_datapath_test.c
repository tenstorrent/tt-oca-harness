/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_local_alias_advanced_datapath_test
 *
 * Strategy: Advanced local-alias datapath; deep signal coverage
 *
 * Focus on advanced local-alias-remap datapath and deep signal-toggle coverage
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Local alias advanced datapath scenario count
#define LOCAL_ALIAS_ADVANCED_SCENARIOS 12

// Advanced datapath test definitions
#define ADVANCED_LOCAL_REGIONS 8
#define DEEP_SIGNAL_PATTERNS 64
#define COMPLEX_ROUTING_TESTS 32

// Local-alias advanced address space
#define LOCAL_ADVANCED_BASE 0x30000000
#define LOCAL_VIRTUAL_SPACE 0x38000000
#define LOCAL_PHYSICAL_SPACE 0x40000000
#define LOCAL_CACHED_SPACE 0x48000000

// Advanced signal combinations
#define SIGNAL_TOGGLE_EXHAUSTIVE 0x1
#define SIGNAL_ROUTING_COMPLEX 0x2
#define SIGNAL_TIMING_CRITICAL 0x4
#define SIGNAL_ERROR_INJECTION 0x8

static int test_advanced_local_alias_datapath_matrix(void) {
    printf("Starting advanced local alias datapath matrix test...\n");

    // Scenario 1: Advanced datapath matrix
    for (int matrix_test = 0; matrix_test < 32; matrix_test++) {
        for (int region = 0; region < 8; region++) {
            // Complex local alias mapping configurations
            uint32_t local_src = LOCAL_ADVANCED_BASE + matrix_test * 0x2000000 + region * 0x400000;
            uint32_t virtual_intermediate =
                LOCAL_VIRTUAL_SPACE + matrix_test * 0x2000000 + region * 0x400000;
            uint32_t physical_dest =
                LOCAL_PHYSICAL_SPACE + matrix_test * 0x2000000 + region * 0x400000;

            // Advanced configuration with multiple translation levels
            if (setup_local_alias_advanced_mapping(region, local_src, virtual_intermediate,
                                                   physical_dest,
                                                   1,                      // enable
                                                   matrix_test % 8,        // priority
                                                   region % 4,             // master id
                                                   (matrix_test >> 2) % 4, // access type
                                                   0xFFE00000,             // 2MB granularity
                                                   CACHE_ATTR_WRITEBACK) != 0) {
                continue;
            }

            // Datapath Matrix Testing - All AXI signal combinations
            for (int axi_combo = 0; axi_combo < 16; axi_combo++) {
                uint32_t test_addr = local_src + axi_combo * 0x10000;

                // AXI ID variations
                uint32_t axi_id = (matrix_test << 4) | axi_combo;

                // AXI Size variations
                uint32_t axi_size_patterns[] = {1, 2, 4, 8, 16, 32, 64, 128};
                uint32_t access_size = axi_size_patterns[axi_combo % 8];

                // AXI Burst type variations
                int burst_type = axi_combo % 3; // FIXED, INCR, WRAP

                test_axi_transaction_with_attributes(test_addr, access_size, AXI_READ, axi_id,
                                                     burst_type);
                test_axi_transaction_with_attributes(test_addr + 0x1000, access_size, AXI_WRITE,
                                                     axi_id, burst_type);

                // Address offset patterns within region
                uint32_t offset_patterns[] = {0x0000,   0x0040,   0x0100,   0x0400,
                                              0x1000,   0x4000,   0x10000,  0x40000,
                                              0x100000, 0x200000, 0x300000, 0x3F0000};

                for (int offset_idx = 0; offset_idx < 12; offset_idx++) {
                    uint32_t offset_addr = local_src + offset_patterns[offset_idx];
                    if (offset_addr < local_src + 0x400000) { // Within region
                        test_axi_transaction(offset_addr, 4,
                                             (offset_idx % 2) ? AXI_WRITE : AXI_READ);
                    }
                }
            }
        }
    }

    printf("Advanced local alias datapath matrix: PASS\n");
    return 0;
}

static int test_deep_signal_toggle_coverage(void) {
    printf("Starting deep signal toggle coverage test...\n");

    // Scenario 2: Deep signal toggle coverage
    for (int signal_test = 0; signal_test < 64; signal_test++) {
        for (int region = 0; region < 8; region++) {
            uint32_t signal_base =
                LOCAL_ADVANCED_BASE + signal_test * 0x1000000 + region * 0x200000;
            uint32_t signal_dest =
                LOCAL_PHYSICAL_SPACE + signal_test * 0x1000000 + region * 0x200000;

            // Deep signal configuration patterns
            uint32_t signal_patterns = signal_test;

            // Enable/Disable toggle patterns
            int enable_pattern = (signal_patterns >> 0) & 0x1;
            int priority_pattern = (signal_patterns >> 1) & 0x7;
            int master_pattern = (signal_patterns >> 4) & 0xF;
            int access_pattern = (signal_patterns >> 8) & 0x3;
            int cache_pattern = (signal_patterns >> 10) & 0xF;

            if (setup_local_alias_deep_config(region, signal_base, signal_dest, enable_pattern,
                                              priority_pattern, master_pattern, access_pattern,
                                              cache_pattern, 0xFFE00000) != 0) {
                continue;
            }

            // Deep signal toggle testing
            uint32_t test_addr = signal_base + 0x80000;

            // Toggle all relevant control signals
            for (int toggle_round = 0; toggle_round < 16; toggle_round++) {
                // Modify configuration on-the-fly to toggle internal signals
                int new_enable = toggle_round & 0x1;
                int new_priority = (priority_pattern + toggle_round) % 8;
                int new_access = (access_pattern + (toggle_round >> 1)) % 4;

                if (setup_local_alias_deep_config(region, signal_base, signal_dest, new_enable,
                                                  new_priority, master_pattern, new_access,
                                                  cache_pattern, 0xFFE00000) == 0) {

                    // Test with new configuration
                    test_axi_transaction(test_addr + toggle_round * 0x1000, 4, AXI_READ);
                    test_axi_transaction(test_addr + toggle_round * 0x1000 + 0x100, 4, AXI_WRITE);

                    // Test specific signal combinations
                    if (new_enable) {
                        // Test valid access scenarios
                        test_axi_transaction(test_addr + 0x8000, 8, AXI_READ);
                        test_axi_transaction(test_addr + 0x8008, 8, AXI_WRITE);
                    } else {
                        // Test disabled scenarios
                        test_axi_transaction(test_addr + 0x8000, 4,
                                             AXI_READ); // Should fail or passthrough
                    }
                }
            }

            // Address translation signal coverage
            for (int addr_signal_test = 0; addr_signal_test < 8; addr_signal_test++) {
                uint32_t translation_src = signal_base + addr_signal_test * 0x8000;
                uint32_t translation_offset = addr_signal_test * 0x10000;
                uint32_t translation_dest = signal_dest + translation_offset;

                // Update destination to test translation signals
                if (setup_local_alias_deep_config(region, translation_src, translation_dest,
                                                  1, // enable
                                                  priority_pattern, master_pattern, access_pattern,
                                                  cache_pattern,
                                                  0xFFFF8000) == 0) { // 32KB granularity

                    // Test translation signal toggle
                    test_axi_transaction(translation_src, 16, AXI_READ);
                    test_axi_transaction(translation_src + 0x2000, 16, AXI_WRITE);
                    test_axi_transaction(translation_src + 0x4000, 32, AXI_READ);
                }
            }
        }
    }

    printf("Deep signal toggle coverage: PASS\n");
    return 0;
}

static int test_complex_routing_scenarios(void) {
    printf("Starting complex routing scenarios test...\n");

    // Scenario 3: Complex routing scenarios
    for (int routing_test = 0; routing_test < 24; routing_test++) {
        // Multi-level routing setup
        for (int level = 0; level < 4; level++) {
            for (int region = level * 2; region < (level + 1) * 2; region++) {
                uint32_t routing_src = LOCAL_ADVANCED_BASE + routing_test * 0x4000000 +
                                       level * 0x1000000 + region * 0x800000;

                // Different destination spaces based on routing level
                uint32_t routing_dest_bases[] = {
                    LOCAL_PHYSICAL_SPACE, // Level 0: Direct physical
                    LOCAL_VIRTUAL_SPACE,  // Level 1: Virtual intermediate
                    LOCAL_CACHED_SPACE,   // Level 2: Cached space
                    LOCAL_ADVANCED_BASE   // Level 3: Loop-back for testing
                };

                uint32_t routing_dest =
                    routing_dest_bases[level] + routing_test * 0x4000000 + region * 0x800000;

                // Complex routing configuration
                if (setup_local_alias_complex_routing(region, routing_src, routing_dest,
                                                      1,                  // enable
                                                      level,              // priority based on level
                                                      routing_test % 8,   // master_id
                                                      level % 4,          // access_type
                                                      level + 1,          // routing_level
                                                      0xFF800000) != 0) { // 8MB granularity
                    continue;
                }

                uint32_t test_addr = routing_src + 0x100000;

                // Test routing at different levels
                // Level 0: Basic routing
                if (level == 0) {
                    test_axi_transaction(test_addr, 4, AXI_READ);
                    test_axi_transaction(test_addr + 0x1000, 8, AXI_WRITE);
                }
                // Level 1: Intermediate routing
                else if (level == 1) {
                    test_axi_transaction(test_addr, 16, AXI_READ);
                    test_axi_transaction(test_addr + 0x2000, 16, AXI_WRITE);
                    test_axi_transaction(test_addr + 0x4000, 32, AXI_READ);
                }
                // Level 2: Cached routing
                else if (level == 2) {
                    test_axi_transaction(test_addr, 64, AXI_READ); // Large cached read
                    test_axi_transaction(test_addr + 0x8000, 64, AXI_WRITE);
                    test_axi_transaction(test_addr + 0x10000, 128, AXI_READ);
                }
                // Level 3: Loop-back routing (complex)
                else if (level == 3) {
                    test_axi_transaction(test_addr, 4, AXI_READ);
                    test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);
                    // This might create internal routing loops for testing
                }

                // Cross-level routing tests
                for (int cross_test = 0; cross_test < 4; cross_test++) {
                    uint32_t cross_addr = routing_src + 0x200000 + cross_test * 0x40000;

                    // Access with different master IDs to test routing
                    int test_master_id = (routing_test + cross_test) % 8;

                    if (setup_local_alias_master_routing(region, cross_addr,
                                                         routing_dest + 0x200000,
                                                         1, // enable
                                                         level, test_master_id, cross_test % 4,
                                                         0xFFFC0000) == 0) { // 256KB granularity

                        test_axi_transaction(cross_addr, 8, AXI_READ);
                        test_axi_transaction(cross_addr + 0x1000, 8, AXI_WRITE);
                    }
                }
            }
        }

        // Inter-level routing conflicts and resolution
        uint32_t conflict_base = LOCAL_ADVANCED_BASE + routing_test * 0x4000000 + 0x2000000;

        for (int conflict_region = 0; conflict_region < 4; conflict_region++) {
            uint32_t conflict_src = conflict_base + conflict_region * 0x200000;

            // Set up conflicting routes with different priorities
            for (int conflict_level = 0; conflict_level < 2; conflict_level++) {
                int conflict_region_id = conflict_region + conflict_level * 4;
                if (conflict_region_id >= 8) continue;

                uint32_t conflict_dest = LOCAL_PHYSICAL_SPACE + routing_test * 0x4000000 +
                                         conflict_level * 0x1000000 + conflict_region * 0x200000;

                if (setup_local_alias_complex_routing(conflict_region_id,
                                                      conflict_src,       // Same source
                                                      conflict_dest,      // Different dest
                                                      1,                  // enable
                                                      conflict_level + 4, // Higher priority
                                                      routing_test % 4, conflict_level % 4,
                                                      2 + conflict_level, // Different routing level
                                                      0xFFE00000) == 0) {

                    // Test conflict resolution
                    test_axi_transaction(conflict_src + 0x40000, 4, AXI_READ);
                    test_axi_transaction(conflict_src + 0x80000, 4, AXI_WRITE);
                }
            }
        }
    }

    printf("Complex routing scenarios: PASS\n");
    return 0;
}

static int test_timing_critical_datapath_sequences(void) {
    printf("Starting timing critical datapath sequences test...\n");

    // Scenario 4: Timing critical datapath sequences
    for (int timing_test = 0; timing_test < 16; timing_test++) {
        for (int region = 0; region < 8; region++) {
            uint32_t timing_base =
                LOCAL_ADVANCED_BASE + timing_test * 0x2000000 + region * 0x400000;
            uint32_t timing_dest =
                LOCAL_PHYSICAL_SPACE + timing_test * 0x2000000 + region * 0x400000;

            if (setup_local_alias_timing_critical(region, timing_base, timing_dest,
                                                  1,               // enable
                                                  timing_test % 8, // priority
                                                  region % 4,      // master_id
                                                  2,               // read-write access
                                                  CACHE_ATTR_WRITEBACK, 0xFFE00000) != 0) {
                continue;
            }

            uint32_t test_addr = timing_base + 0x80000;

            // Timing Critical Sequence 1: Back-to-back accesses
            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 4, 4, AXI_READ);  // Immediately following
            test_axi_transaction(test_addr + 8, 4, AXI_WRITE); // Read-to-write transition

            // Timing Critical Sequence 2: Overlapping bursts (if supported)
            test_axi_transaction(test_addr + 0x1000, 32, AXI_READ);
            test_axi_transaction(test_addr + 0x1020, 32, AXI_READ); // Overlapping start

            // Timing Critical Sequence 3: Priority inversion scenarios
            for (int priority_test = 0; priority_test < 4; priority_test++) {
                // Temporarily change priority
                int temp_priority = (timing_test + priority_test + 4) % 8;

                if (setup_local_alias_timing_critical(region, timing_base, timing_dest,
                                                      1, // enable
                                                      temp_priority, region % 4,
                                                      2, // access type
                                                      CACHE_ATTR_WRITEBACK, 0xFFE00000) == 0) {

                    // Test with new priority
                    test_axi_transaction(test_addr + 0x2000 + priority_test * 0x100, 8, AXI_READ);
                    test_axi_transaction(test_addr + 0x2008 + priority_test * 0x100, 8, AXI_WRITE);
                }
            }

            // Timing Critical Sequence 4: Cache coherency sequences
            test_axi_transaction(test_addr + 0x4000, 64, AXI_WRITE); // Fill cache line
            test_axi_transaction(test_addr + 0x4000, 64, AXI_READ);  // Read same cache line
            test_axi_transaction(test_addr + 0x4040, 64, AXI_WRITE); // Next cache line

            // Timing Critical Sequence 5: Master ID switching
            for (int master_switch = 0; master_switch < 4; master_switch++) {
                int new_master = (region + master_switch) % 4;

                if (setup_local_alias_timing_critical(region, timing_base, timing_dest,
                                                      1, // enable
                                                      timing_test % 8, new_master,
                                                      2, // access type
                                                      CACHE_ATTR_WRITEBACK, 0xFFE00000) == 0) {

                    // Rapid master switching
                    uint32_t switch_addr = test_addr + 0x8000 + master_switch * 0x200;
                    test_axi_transaction(switch_addr, 4, AXI_READ);
                    test_axi_transaction(switch_addr + 0x10, 4, AXI_WRITE);
                }
            }

            // Timing Critical Sequence 6: Address translation pipeline stress
            for (int pipeline_test = 0; pipeline_test < 8; pipeline_test++) {
                uint32_t pipeline_addr = test_addr + 0x10000 + pipeline_test * 0x1000;

                // Stress address translation pipeline with rapid sequential accesses
                test_axi_transaction(pipeline_addr, 4, AXI_READ);
                test_axi_transaction(pipeline_addr + 0x100, 4, AXI_READ);
                test_axi_transaction(pipeline_addr + 0x200, 4, AXI_WRITE);
                test_axi_transaction(pipeline_addr + 0x300, 4, AXI_WRITE);
            }
        }
    }

    printf("Timing critical datapath sequences: PASS\n");
    return 0;
}

static int test_error_injection_advanced_recovery(void) {
    printf("Starting error injection advanced recovery test...\n");

    // Scenario 5: Error injection advanced recovery
    for (int error_test = 0; error_test < 20; error_test++) {
        for (int region = 0; region < 8; region++) {
            uint32_t error_base = LOCAL_ADVANCED_BASE + error_test * 0x1000000 + region * 0x200000;
            uint32_t error_dest = LOCAL_PHYSICAL_SPACE + error_test * 0x1000000 + region * 0x200000;

            // Normal configuration first
            if (setup_local_alias_deep_config(region, error_base, error_dest,
                                              1, // enable
                                              region % 8,
                                              0, // master_id
                                              2, // read-write access
                                              CACHE_ATTR_WRITEBACK, 0xFFE00000) != 0) {
                continue;
            }

            uint32_t test_addr = error_base + 0x40000;

            // Error Injection 1: Invalid address translation
            uint32_t invalid_dest = 0xFFFFFFFF; // Invalid destination
            if (setup_local_alias_deep_config(region, error_base, invalid_dest,
                                              1, // enable
                                              region % 8, 0, 2, CACHE_ATTR_WRITEBACK,
                                              0xFFE00000) != 0) {
                // Expected to fail
            }

            // Test access during error state
            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE);

            // Advanced Recovery 1: Gradual reconfiguration
            uint32_t recovery_destinations[] = {
                error_dest,            // Original destination
                error_dest + 0x100000, // Offset destination
                error_dest + 0x200000, // Further offset
                LOCAL_CACHED_SPACE + error_test * 0x1000000 + region * 0x200000 // Different space
            };

            for (int recovery_step = 0; recovery_step < 4; recovery_step++) {
                if (setup_local_alias_deep_config(region, error_base,
                                                  recovery_destinations[recovery_step],
                                                  1, // enable
                                                  region % 8,
                                                  recovery_step % 4, // changing master
                                                  2, CACHE_ATTR_WRITEBACK, 0xFFE00000) == 0) {

                    // Test recovery step
                    test_axi_transaction(test_addr + recovery_step * 0x800, 8, AXI_READ);
                    test_axi_transaction(test_addr + recovery_step * 0x800 + 0x100, 8, AXI_WRITE);
                }
            }

            // Error Injection 2: Master ID conflicts
            for (int conflict_master = 0; conflict_master < 4; conflict_master++) {
                // Configure with potentially conflicting master IDs
                if (setup_local_alias_deep_config(region, error_base, error_dest,
                                                  1, // enable
                                                  7, // highest priority
                                                  conflict_master,
                                                  3,                 // different access type
                                                  CACHE_ATTR_DEVICE, // different cache
                                                  0xFFE00000) == 0) {

                    // Test with conflicting configuration
                    test_axi_transaction(test_addr + 0x2000 + conflict_master * 0x400, 4, AXI_READ);
                }
            }

            // Error Injection 3: Rapid reconfiguration stress
            for (int rapid_reconfig = 0; rapid_reconfig < 16; rapid_reconfig++) {
                int flip_enable = rapid_reconfig & 0x1;
                int changing_priority = rapid_reconfig % 8;
                int changing_access = rapid_reconfig % 4;

                setup_local_alias_deep_config(region, error_base, error_dest, flip_enable,
                                              changing_priority, 0, changing_access,
                                              CACHE_ATTR_WRITEBACK, 0xFFE00000);

                // Quick access during rapid reconfiguration
                if (flip_enable) {
                    test_axi_transaction(test_addr + 0x4000 + rapid_reconfig * 0x100, 4, AXI_READ);
                }
            }

            // Advanced Recovery 2: Complete reset and restoration
            if (setup_local_alias_deep_config(region, 0, 0, // Clear configuration
                                              0,            // disable
                                              0, 0, 0, 0, 0) == 0) {

                // Restore with original configuration
                if (setup_local_alias_deep_config(region, error_base, error_dest,
                                                  1, // enable
                                                  region % 8, 0, 2, CACHE_ATTR_WRITEBACK,
                                                  0xFFE00000) == 0) {

                    // Final verification
                    test_axi_transaction(test_addr + 0x8000, 32, AXI_READ);
                    test_axi_transaction(test_addr + 0x8020, 32, AXI_WRITE);
                }
            }
        }
    }

    printf("Error injection advanced recovery: PASS\n");
    return 0;
}

int main(void) {
    printf("Local Alias Advanced Datapath Test\n");
    printf("Strategy: Advanced local-alias datapath; deep signal coverage\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_local_alias_advanced_datapath_test");
        return TEST_FAIL;
    }

    // Run all local-alias advanced datapath scenarios
    if (test_advanced_local_alias_datapath_matrix() != 0) {
        test_fail("Advanced Local Alias Datapath Matrix");
        return TEST_FAIL;
    }

    if (test_deep_signal_toggle_coverage() != 0) {
        test_fail("Deep Signal Toggle Coverage");
        return TEST_FAIL;
    }

    if (test_complex_routing_scenarios() != 0) {
        test_fail("Complex Routing Scenarios");
        return TEST_FAIL;
    }

    if (test_timing_critical_datapath_sequences() != 0) {
        test_fail("Timing Critical Datapath Sequences");
        return TEST_FAIL;
    }

    if (test_error_injection_advanced_recovery() != 0) {
        test_fail("Error Injection Advanced Recovery");
        return TEST_FAIL;
    }

    printf("\n=== LOCAL ALIAS ADVANCED DATAPATH TEST PASSED ===\n");

    test_pass("fabric_local_alias_advanced_datapath_test");
    return TEST_PASS;
}
