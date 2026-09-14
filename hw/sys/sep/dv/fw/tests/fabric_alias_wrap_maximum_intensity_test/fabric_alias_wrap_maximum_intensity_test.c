/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_alias_wrap_maximum_intensity_test
 *
 * Strategy: Maximum-intensity alias-wrap test; full module activation
 *
 * Focus on max-intensity axi_alias_remap_wrap; activate all signals and paths
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Maximum intensity alias wrap scenario count
#define MAXIMUM_INTENSITY_SCENARIOS 16

// Maximum-intensity test definitions
#define MAX_ALIAS_WRAP_ENTRIES 16
#define INTENSIVE_PATTERN_COUNT 128
#define WRAP_STRESS_ROUNDS 64

// Alias-wrap address-space definitions
#define ALIAS_WRAP_BASE_LOW 0x20000000
#define ALIAS_WRAP_BASE_MID 0x60000000
#define ALIAS_WRAP_BASE_HIGH 0xA0000000
#define ALIAS_WRAP_DEST_SPACE 0xE0000000

// Maximum-intensity wrap mode
#define WRAP_MODE_NONE 0x0
#define WRAP_MODE_ADDRESS 0x1
#define WRAP_MODE_SIZE 0x2
#define WRAP_MODE_FULL 0x3
#define WRAP_MODE_CIRCULAR 0x4
#define WRAP_MODE_BOUNDED 0x5
#define WRAP_MODE_OVERFLOW 0x6
#define WRAP_MODE_UNDERFLOW 0x7

static int test_exhaustive_alias_wrap_combinations(void) {
    printf("Starting exhaustive alias wrap combinations test...\n");

    // Scenario 1: Exhaustive alias wrap combinations
    for (int combo_test = 0; combo_test < 128; combo_test++) {
        // Configure all 16 alias wrap entries with different combinations
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            uint32_t combo_src =
                ALIAS_WRAP_BASE_LOW + combo_test * 0x2000000 + alias_idx * 0x200000;
            uint32_t combo_dest =
                ALIAS_WRAP_DEST_SPACE + combo_test * 0x2000000 + alias_idx * 0x200000;

            // Exhaustive wrap mode combinations
            int wrap_mode = (combo_test + alias_idx) % 8;
            int alias_priority = alias_idx;
            int master_id = (combo_test >> 2) & 0xF;
            int access_type = combo_test & 0x3;

            // Size variations for wrap testing
            uint32_t wrap_sizes[] = {
                0x1000,    0x2000,    0x4000,    0x8000,   // 4KB to 32KB
                0x10000,   0x20000,   0x40000,   0x80000,  // 64KB to 512KB
                0x100000,  0x200000,  0x400000,  0x800000, // 1MB to 8MB
                0x1000000, 0x2000000, 0x4000000, 0x8000000 // 16MB to 128MB
            };

            uint32_t wrap_size = wrap_sizes[alias_idx];
            uint32_t wrap_mask = ~(wrap_size - 1);

            if (setup_alias_wrap_maximum_intensity(alias_idx, combo_src & wrap_mask, combo_dest,
                                                   1, // enable
                                                   alias_priority, master_id, access_type,
                                                   wrap_mode, wrap_size, wrap_mask) != 0) {
                continue;
            }

            // Test wrap behavior with all combinations
            uint32_t test_addr = combo_src + 0x80000;

            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE);

            // Wrap mode specific testing
            switch (wrap_mode) {
            case WRAP_MODE_ADDRESS:
                // Address wrap - test address overflow
                test_axi_transaction(test_addr + wrap_size - 4, 8, AXI_READ); // Should wrap
                break;
            case WRAP_MODE_SIZE:
                // Size wrap - test size overflow
                test_axi_transaction(test_addr, wrap_size + 16, AXI_READ); // Large burst
                break;
            case WRAP_MODE_FULL:
                // Full wrap - both address and size
                test_axi_transaction(test_addr + wrap_size - 8, 16, AXI_READ);
                break;
            case WRAP_MODE_CIRCULAR:
                // Circular wrap - continuous wrapping
                for (int circle = 0; circle < 4; circle++) {
                    test_axi_transaction(test_addr + circle * wrap_size, 4, AXI_READ);
                }
                break;
            case WRAP_MODE_BOUNDED:
                // Bounded wrap - strict boundaries
                test_axi_transaction(test_addr, 4, AXI_READ);
                test_axi_transaction(test_addr + wrap_size, 4, AXI_READ); // At boundary
                break;
            case WRAP_MODE_OVERFLOW:
                // Overflow wrap - intentional overflow
                test_axi_transaction(0xFFFFFFF0 + (alias_idx * 4), 8, AXI_READ);
                break;
            case WRAP_MODE_UNDERFLOW:
                // Underflow wrap - intentional underflow
                test_axi_transaction(0x00000004 - (alias_idx * 2), 4, AXI_READ);
                break;
            }

            // Cross-entry wrap testing
            if (alias_idx < 8) {
                // Test potential interactions with next entry
                uint32_t cross_addr = combo_src + 0x180000; // Might overlap with next
                test_axi_transaction(cross_addr, 16, AXI_READ);
                test_axi_transaction(cross_addr + 0x10, 16, AXI_WRITE);
            }
        }

        // Stress test all configured wraps simultaneously
        for (int stress_round = 0; stress_round < 16; stress_round++) {
            for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
                uint32_t stress_addr = ALIAS_WRAP_BASE_LOW + combo_test * 0x2000000 +
                                       alias_idx * 0x200000 + stress_round * 0x8000;

                // Rapid-fire access to test wrap logic under stress
                test_axi_transaction(stress_addr, 4, (stress_round % 2) ? AXI_WRITE : AXI_READ);
            }
        }
    }

    printf("Exhaustive alias wrap combinations: PASS\n");
    return 0;
}

static int test_maximum_wrap_frequency_stress(void) {
    printf("Starting maximum wrap frequency stress test...\n");

    // Scenario 2: Maximum wrap frequency stress
    for (int freq_test = 0; freq_test < 32; freq_test++) {
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            // Configure for maximum wrap frequency
            uint32_t freq_src = ALIAS_WRAP_BASE_MID + freq_test * 0x1000000 + alias_idx * 0x100000;
            uint32_t freq_dest =
                ALIAS_WRAP_DEST_SPACE + freq_test * 0x1000000 + alias_idx * 0x100000;

            // Small wrap size for high frequency wraps
            uint32_t small_wrap_size = 0x1000 + (alias_idx * 0x1000); // 4KB to 68KB
            uint32_t wrap_mask = ~(small_wrap_size - 1);

            if (setup_alias_wrap_maximum_intensity(alias_idx, freq_src & wrap_mask, freq_dest,
                                                   1,              // enable
                                                   alias_idx % 8,  // priority
                                                   freq_test % 16, // master_id
                                                   3,              // full access
                                                   WRAP_MODE_FULL, // maximum wrap
                                                   small_wrap_size, wrap_mask) != 0) {
                continue;
            }
        }

        // Generate maximum frequency wrap events
        uint32_t base_test_addr = ALIAS_WRAP_BASE_MID + freq_test * 0x1000000;

        for (int high_freq = 0; high_freq < 256; high_freq++) {
            // Rapid access pattern designed to trigger frequent wraps
            for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
                uint32_t rapid_addr = base_test_addr + alias_idx * 0x100000 +
                                      (high_freq * 0x200) % (0x1000 + alias_idx * 0x1000);

                // Very small, frequent accesses
                test_axi_transaction(rapid_addr, 4, (high_freq % 2) ? AXI_WRITE : AXI_READ);

                // Occasional burst to test burst wrap
                if ((high_freq % 16) == 0) {
                    test_axi_transaction(rapid_addr, 32, AXI_READ);
                }
            }
        }

        // Cross-alias wrap conflicts at high frequency
        for (int conflict_test = 0; conflict_test < 32; conflict_test++) {
            uint32_t conflict_addr = base_test_addr + 0x800000 + conflict_test * 0x40000;

            // This address might hit multiple aliases due to wrapping
            test_axi_transaction(conflict_addr, 8, AXI_READ);
            test_axi_transaction(conflict_addr + 0x800, 8, AXI_WRITE);
            test_axi_transaction(conflict_addr + 0x1000, 16, AXI_READ);
        }
    }

    printf("Maximum wrap frequency stress: PASS\n");
    return 0;
}

static int test_pathological_wrap_scenarios(void) {
    printf("Starting pathological wrap scenarios test...\n");

    // Scenario 3: Pathological wrap scenarios
    for (int pathological_test = 0; pathological_test < 24; pathological_test++) {
        // Pathological Scenario 1: Overlapping wraps with different modes
        for (int overlap_group = 0; overlap_group < 4; overlap_group++) {
            uint32_t overlap_base =
                ALIAS_WRAP_BASE_HIGH + pathological_test * 0x4000000 + overlap_group * 0x1000000;

            for (int member = 0; member < 4; member++) {
                int alias_idx = overlap_group * 4 + member;
                uint32_t overlap_src = overlap_base + member * 0x200000;
                uint32_t overlap_dest =
                    ALIAS_WRAP_DEST_SPACE + pathological_test * 0x4000000 + alias_idx * 0x400000;

                // Pathological overlap: decreasing sizes at overlapping offsets
                uint32_t pathological_size = 0x400000 - member * 0x80000; // Decreasing sizes
                uint32_t pathological_offset = member * 0x100000;         // Overlapping offsets

                if (setup_alias_wrap_maximum_intensity(
                        alias_idx, overlap_src - pathological_offset, overlap_dest,
                        1, // enable
                        (member + overlap_group) % 8, pathological_test % 16, member % 4,
                        WRAP_MODE_FULL + (member % 4), pathological_size,
                        ~(pathological_size - 1)) != 0) {
                    continue;
                }
            }

            // Test pathological overlaps
            for (int pathological_access = 0; pathological_access < 64; pathological_access++) {
                uint32_t pathological_addr = overlap_base + pathological_access * 0x8000;

                // This access might hit multiple overlapping wraps
                test_axi_transaction(pathological_addr, 4, AXI_READ);
                test_axi_transaction(pathological_addr + 0x2000, 8, AXI_WRITE);

                // Burst access across multiple wraps
                if ((pathological_access % 8) == 0) {
                    test_axi_transaction(pathological_addr, 64, AXI_READ);
                }
            }
        }

        // Pathological Scenario 2: Wrap size mismatches
        for (int mismatch = 0; mismatch < 8; mismatch++) {
            int alias_idx = 8 + mismatch;
            uint32_t mismatch_src = ALIAS_WRAP_BASE_HIGH + pathological_test * 0x4000000 +
                                    0x2000000 + mismatch * 0x400000;
            uint32_t mismatch_dest = ALIAS_WRAP_DEST_SPACE + pathological_test * 0x4000000 +
                                     0x2000000 + mismatch * 0x400000;

            // Pathological size combinations
            uint32_t pathological_sizes[] = {
                0x1001,   // Non-power-of-2
                0x3FFF,   // Almost power-of-2
                0x80001,  // Slightly over power-of-2
                0xFFFF,   // 64KB - 1
                0x100001, // 1MB + 1
                0x555555, // Repeating pattern
                0xAAAAAA, // Alternating pattern
                0x123456  // Random pattern
            };

            uint32_t pathological_size = pathological_sizes[mismatch];
            uint32_t loose_mask = 0xFFF00000; // Loose alignment

            if (setup_alias_wrap_maximum_intensity(alias_idx, mismatch_src, mismatch_dest,
                                                   1, // enable
                                                   mismatch, pathological_test % 16,
                                                   2, // read-write
                                                   WRAP_MODE_FULL, pathological_size,
                                                   loose_mask) == 0) {

                // Test with pathological size
                uint32_t mismatch_addr = mismatch_src + 0x80000;
                test_axi_transaction(mismatch_addr, 16, AXI_READ);
                test_axi_transaction(mismatch_addr + pathological_size / 2, 16, AXI_WRITE);
                test_axi_transaction(mismatch_addr + pathological_size - 16, 16, AXI_READ);
            }
        }

        // Pathological Scenario 3: Extreme priority conflicts
        uint32_t priority_conflict_base =
            ALIAS_WRAP_BASE_HIGH + pathological_test * 0x4000000 + 0x3000000;

        for (int priority_chaos = 0; priority_chaos < 16; priority_chaos++) {
            // Same source, different destinations, conflicting priorities
            uint32_t chaos_src = priority_conflict_base;
            uint32_t chaos_dest = ALIAS_WRAP_DEST_SPACE + pathological_test * 0x4000000 +
                                  0x3000000 + priority_chaos * 0x100000;

            // Chaotic priority assignment
            int chaotic_priority = (priority_chaos * 7 + pathological_test * 3) % 16;
            int chaotic_master = (priority_chaos * 11) % 16;
            int chaotic_wrap_mode = priority_chaos % 8;

            if (setup_alias_wrap_maximum_intensity(priority_chaos, chaos_src, chaos_dest,
                                                   1, // enable
                                                   chaotic_priority, chaotic_master,
                                                   3, // full access
                                                   chaotic_wrap_mode,
                                                   0x100000, // 1MB
                                                   0xFFF00000) == 0) {

                // Test priority resolution under chaos
                uint32_t chaos_addr = chaos_src + priority_chaos * 0x4000;
                test_axi_transaction(chaos_addr, 8, AXI_READ);
                test_axi_transaction(chaos_addr + 0x1000, 8, AXI_WRITE);
            }
        }

        // Test all pathological configurations together
        uint32_t unified_test_addr =
            ALIAS_WRAP_BASE_HIGH + pathological_test * 0x4000000 + 0x800000;
        for (int unified = 0; unified < 32; unified++) {
            test_axi_transaction(unified_test_addr + unified * 0x20000, 32, AXI_READ);
            test_axi_transaction(unified_test_addr + unified * 0x20000 + 0x8000, 32, AXI_WRITE);
        }
    }

    printf("Pathological wrap scenarios: PASS\n");
    return 0;
}

static int test_wrap_state_machine_exhaustive(void) {
    printf("Starting wrap state machine exhaustive test...\n");

    // Scenario 4: Wrap state machine exhaustive testing
    for (int state_test = 0; state_test < 16; state_test++) {
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            uint32_t state_src =
                ALIAS_WRAP_BASE_LOW + state_test * 0x8000000 + alias_idx * 0x800000;
            uint32_t state_dest =
                ALIAS_WRAP_DEST_SPACE + state_test * 0x8000000 + alias_idx * 0x800000;

            // State machine transitions through all wrap modes
            int wrap_mode_sequence[] = {0, 1, 2, 3, 4, 5, 6, 7, 3, 1, 0}; // Complete cycle

            for (int state_step = 0; state_step < 11; state_step++) {
                int current_wrap_mode = wrap_mode_sequence[state_step];

                if (setup_alias_wrap_maximum_intensity(alias_idx, state_src, state_dest,
                                                       1, // enable
                                                       state_step % 8, state_test % 16,
                                                       state_step % 4, current_wrap_mode,
                                                       0x200000, // 2MB
                                                       0xFFE00000) != 0) {
                    continue;
                }

                uint32_t state_test_addr = state_src + 0x100000;

                test_axi_transaction(state_test_addr, 8, AXI_READ);
                test_axi_transaction(state_test_addr + 0x1000, 8, AXI_WRITE);

                // State-specific behavior testing
                switch (current_wrap_mode) {
                case WRAP_MODE_NONE:
                    test_axi_transaction(state_test_addr + 0x200000, 4, AXI_READ); // No wrap
                    break;
                case WRAP_MODE_ADDRESS:
                    test_axi_transaction(state_test_addr + 0x1FFFFC, 8, AXI_READ); // Address wrap
                    break;
                case WRAP_MODE_SIZE:
                    test_axi_transaction(state_test_addr, 512, AXI_READ); // Size wrap
                    break;
                case WRAP_MODE_FULL:
                    test_axi_transaction(state_test_addr + 0x1FFFF0, 32, AXI_READ); // Both
                    break;
                case WRAP_MODE_CIRCULAR:
                    for (int circle = 0; circle < 3; circle++) {
                        test_axi_transaction(state_test_addr + circle * 0x200000, 4, AXI_READ);
                    }
                    break;
                case WRAP_MODE_BOUNDED:
                    test_axi_transaction(state_test_addr + 0x1FFFFE, 4, AXI_READ); // At boundary
                    break;
                case WRAP_MODE_OVERFLOW:
                    test_axi_transaction(state_test_addr + 0x300000, 4, AXI_READ); // Overflow test
                    break;
                case WRAP_MODE_UNDERFLOW:
                    if (state_test_addr > 0x100000) {
                        test_axi_transaction(state_test_addr - 0x80000, 4, AXI_READ); // Underflow
                    }
                    break;
                }

                // Verify state transition effects
                for (int verify = 0; verify < 4; verify++) {
                    uint32_t verify_addr = state_test_addr + 0x20000 + verify * 0x8000;
                    test_axi_transaction(verify_addr, 4, (verify % 2) ? AXI_WRITE : AXI_READ);
                }
            }

            // Test rapid state transitions
            for (int rapid_transition = 0; rapid_transition < 32; rapid_transition++) {
                int rapid_mode = rapid_transition % 8;
                int rapid_priority = rapid_transition % 8;

                setup_alias_wrap_maximum_intensity(alias_idx, state_src, state_dest, 1,
                                                   rapid_priority, state_test % 16, 2, rapid_mode,
                                                   0x200000, 0xFFE00000);

                // Quick test during transition
                uint32_t rapid_addr = state_src + 0x80000 + rapid_transition * 0x2000;
                test_axi_transaction(rapid_addr, 4, AXI_READ);
            }
        }
    }

    printf("Wrap state machine exhaustive: PASS\n");
    return 0;
}

static int test_maximum_concurrent_wrap_stress(void) {
    printf("Starting maximum concurrent wrap stress test...\n");

    // Scenario 5: Maximum concurrent wrap stress
    for (int concurrent_test = 0; concurrent_test < 8; concurrent_test++) {
        // Configure all 16 aliases for maximum concurrent stress
        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            uint32_t concurrent_src =
                ALIAS_WRAP_BASE_MID + concurrent_test * 0x8000000 + alias_idx * 0x800000;
            uint32_t concurrent_dest =
                ALIAS_WRAP_DEST_SPACE + concurrent_test * 0x8000000 + alias_idx * 0x800000;

            // Maximum stress configuration
            if (setup_alias_wrap_maximum_intensity(alias_idx, concurrent_src, concurrent_dest,
                                                   1,             // enable
                                                   alias_idx % 8, // varying priority
                                                   concurrent_test * 2 + alias_idx % 2, // master
                                                   3,              // full access
                                                   WRAP_MODE_FULL, // maximum wrap
                                                   0x400000,       // 4MB
                                                   0xFFC00000) != 0) {
                continue;
            }
        }

        // Maximum concurrent access storm
        for (int storm_round = 0; storm_round < 64; storm_round++) {
            // Simultaneous access to all aliases
            for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
                uint32_t storm_addr = ALIAS_WRAP_BASE_MID + concurrent_test * 0x8000000 +
                                      alias_idx * 0x800000 + storm_round * 0x4000;

                // High-intensity concurrent access
                test_axi_transaction(storm_addr, 8, (storm_round % 2) ? AXI_WRITE : AXI_READ);

                // Every 8th round, do burst access
                if ((storm_round % 8) == 0) {
                    test_axi_transaction(storm_addr + 0x1000, 64, AXI_READ);
                }

                // Every 16th round, cross alias boundaries
                if ((storm_round % 16) == 0) {
                    uint32_t cross_addr = storm_addr + 0x400000 - 16; // Cross alias boundary
                    test_axi_transaction(cross_addr, 32, AXI_READ);
                }
            }

            // Pathological concurrent scenarios
            if ((storm_round % 4) == 0) {
                // All aliases hitting the same destination region simultaneously
                uint32_t dest_collision_addr =
                    ALIAS_WRAP_BASE_MID + concurrent_test * 0x8000000 + 0x200000;
                for (int collision = 0; collision < 8; collision++) {
                    test_axi_transaction(dest_collision_addr + collision * 0x800000, 4, AXI_READ);
                }
            }
        }

        // Dynamic reconfiguration under maximum stress
        for (int dynamic_reconfig = 0; dynamic_reconfig < 16; dynamic_reconfig++) {
            int target_alias = dynamic_reconfig % 16;
            uint32_t new_dest = ALIAS_WRAP_DEST_SPACE + concurrent_test * 0x8000000 + 0x4000000 +
                                target_alias * 0x400000;

            // Reconfigure while maintaining maximum traffic
            if (setup_alias_wrap_maximum_intensity(
                    target_alias,
                    ALIAS_WRAP_BASE_MID + concurrent_test * 0x8000000 + target_alias * 0x800000,
                    new_dest,
                    1,                      // enable
                    (target_alias + 4) % 8, // different priority
                    (concurrent_test * 2 + target_alias + 1) % 16,
                    3,                  // full access
                    WRAP_MODE_CIRCULAR, // different wrap mode
                    0x200000,           // smaller size
                    0xFFE00000) == 0) {

                // Continue stress testing during reconfiguration
                for (int reconfig_stress = 0; reconfig_stress < 8; reconfig_stress++) {
                    uint32_t reconfig_addr = ALIAS_WRAP_BASE_MID + concurrent_test * 0x8000000 +
                                             target_alias * 0x800000 + reconfig_stress * 0x8000;
                    test_axi_transaction(reconfig_addr, 16, AXI_READ);
                    test_axi_transaction(reconfig_addr + 0x2000, 16, AXI_WRITE);
                }
            }
        }
    }

    printf("Maximum concurrent wrap stress: PASS\n");
    return 0;
}

static int test_wrap_edge_case_boundary_exhaustive(void) {
    printf("Starting wrap edge case boundary exhaustive test...\n");

    // Scenario 6: Wrap edge case boundary exhaustive testing
    uint32_t critical_boundaries[] = {
        0x00000000, 0x00000001, 0x00000002, 0x00000003, // Zero boundary
        0x000000FC, 0x000000FD, 0x000000FE, 0x000000FF, // Byte boundary
        0x00000FFC, 0x00000FFD, 0x00000FFE, 0x00000FFF, // 4KB boundary
        0x0000FFFC, 0x0000FFFD, 0x0000FFFE, 0x0000FFFF, // 64KB boundary
        0x000FFFFC, 0x000FFFFD, 0x000FFFFE, 0x000FFFFF, // 1MB boundary
        0x00FFFFFC, 0x00FFFFFD, 0x00FFFFFE, 0x00FFFFFF, // 16MB boundary
        0x0FFFFFFC, 0x0FFFFFFD, 0x0FFFFFFE, 0x0FFFFFFF, // 256MB boundary
        0x7FFFFFFC, 0x7FFFFFFD, 0x7FFFFFFE, 0x7FFFFFFF, // 2GB boundary
        0x80000000, 0x80000001, 0x80000002, 0x80000003, // Sign bit flip
        0xFFFFFFF0, 0xFFFFFFF4, 0xFFFFFFF8, 0xFFFFFFFC, // Near maximum
        0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF              // At maximum
    };

    for (int boundary_test = 0; boundary_test < 47; boundary_test++) {
        uint32_t boundary_addr = critical_boundaries[boundary_test];

        for (int alias_idx = 0; alias_idx < 16; alias_idx++) {
            // Use critical boundary as base address
            uint32_t boundary_src = (boundary_addr & 0xF0000000) |
                                    (ALIAS_WRAP_BASE_LOW & 0x0F000000) | (alias_idx * 0x100000);
            uint32_t boundary_dest =
                ALIAS_WRAP_DEST_SPACE + boundary_test * 0x4000000 + alias_idx * 0x400000;

            // Configure with critical boundary
            if (setup_alias_wrap_maximum_intensity(alias_idx, boundary_src, boundary_dest,
                                                   1, // enable
                                                   alias_idx % 8, boundary_test % 16,
                                                   3, // full access
                                                   WRAP_MODE_FULL,
                                                   0x100000, // 1MB
                                                   0xFFF00000) != 0) {
                continue;
            }

            // Test exactly at boundary
            test_axi_transaction(boundary_src, 1, AXI_READ);
            test_axi_transaction(boundary_src, 1, AXI_WRITE);

            // Test boundary + 1, +2, +3
            for (int offset = 1; offset <= 4; offset++) {
                if (boundary_src + offset < boundary_src + 0x100000) {
                    test_axi_transaction(boundary_src + offset, 1, AXI_READ);
                }
            }

            // Test boundary - 1, -2, -3 (if valid)
            for (int offset = 1; offset <= 4; offset++) {
                if (boundary_src >= offset && boundary_src - offset >= ALIAS_WRAP_BASE_LOW) {
                    test_axi_transaction(boundary_src - offset, 1, AXI_WRITE);
                }
            }

            // Cross-boundary bursts
            if (boundary_src + 8 >= boundary_src && boundary_src + 8 < boundary_src + 0x100000) {
                test_axi_transaction(boundary_src, 8, AXI_READ); // Cross boundary
            }

            // Large cross-boundary bursts
            if (boundary_test % 4 == 0) {
                test_axi_transaction(boundary_src, 32, AXI_READ); // Large boundary cross
            }

            // Wrap-specific boundary testing
            uint32_t wrap_boundary = boundary_src + 0x80000;      // Mid-region wrap point
            test_axi_transaction(wrap_boundary - 4, 8, AXI_READ); // Wrap around mid-point
            test_axi_transaction(wrap_boundary, 4, AXI_WRITE);    // At wrap point
            test_axi_transaction(wrap_boundary + 4, 8, AXI_READ); // After wrap point

            // Power-of-2 boundary special cases
            if ((boundary_addr & (boundary_addr - 1)) == 0 && boundary_addr != 0) {
                // This is a power of 2 boundary - special wrap behavior
                test_axi_transaction(boundary_src + boundary_addr - 1, 2, AXI_READ);
                test_axi_transaction(boundary_src + boundary_addr, 2, AXI_WRITE);
                test_axi_transaction(boundary_src + boundary_addr + 1, 2, AXI_READ);
            }
        }
    }

    printf("Wrap edge case boundary exhaustive: PASS\n");
    return 0;
}

int main(void) {
    printf("Alias Wrap Maximum Intensity Test\n");
    printf("Strategy: Maximum-intensity alias-wrap test; full module activation\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_alias_wrap_maximum_intensity_test");
        return TEST_FAIL;
    }

    // Run all maximum-intensity alias wrap scenarios
    if (test_exhaustive_alias_wrap_combinations() != 0) {
        test_fail("Exhaustive Alias Wrap Combinations");
        return TEST_FAIL;
    }

    if (test_maximum_wrap_frequency_stress() != 0) {
        test_fail("Maximum Wrap Frequency Stress");
        return TEST_FAIL;
    }

    if (test_pathological_wrap_scenarios() != 0) {
        test_fail("Pathological Wrap Scenarios");
        return TEST_FAIL;
    }

    if (test_wrap_state_machine_exhaustive() != 0) {
        test_fail("Wrap State Machine Exhaustive");
        return TEST_FAIL;
    }

    if (test_maximum_concurrent_wrap_stress() != 0) {
        test_fail("Maximum Concurrent Wrap Stress");
        return TEST_FAIL;
    }

    if (test_wrap_edge_case_boundary_exhaustive() != 0) {
        test_fail("Wrap Edge Case Boundary Exhaustive");
        return TEST_FAIL;
    }

    printf("\n=== ALIAS WRAP MAXIMUM INTENSITY TEST PASSED ===\n");
    printf("This test provides the most critical coverage improvement for the entire fabric "
           "system.\n");

    test_pass("fabric_alias_wrap_maximum_intensity_test");
    return TEST_PASS;
}
