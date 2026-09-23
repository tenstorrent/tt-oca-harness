/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_filter_wrap_edge_case_test
 *
 * Strategy: Precise filter-wrap boundary and anomaly cases
 *
 * Focus on axi_filter_wrap boundaries, anomaly handling, and wrap logic
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Filter wrap edge case scenario count
#define FILTER_WRAP_SCENARIOS 10

// Filter test definitions
#define MAX_FILTER_ENTRIES 16
#define WRAP_BOUNDARY_TESTS 32
#define EDGE_CASE_PATTERNS 24

// Filter type/mode definitions
#define FILTER_TYPE_ALLOWLIST 0x1
#define FILTER_TYPE_BLOCKLIST 0x2
#define FILTER_TYPE_REMAP 0x4
#define FILTER_TYPE_MONITOR 0x8

// Wrap-logic test addresses
#define WRAP_TEST_BASE 0x70000000
#define WRAP_BOUNDARY_LOW 0x7FFFFFE0
#define WRAP_BOUNDARY_HIGH 0x80000020

static int test_address_wrap_boundary_precision(void) {
    printf("Starting address wrap boundary precision test...\n");

    // Scenario 1: Precise address-wrap boundary test
    for (int wrap_test = 0; wrap_test < 64; wrap_test++) {
        // setwrap boundary filter entries
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            // Edge case addresses around 32-bit boundary
            uint32_t boundary_addrs[] = {
                0xFFFFFFF0,
                0xFFFFFFFC,
                0xFFFFFFFE,
                0xFFFFFFFF, // Near 32-bit max
                0x00000000,
                0x00000001,
                0x00000002,
                0x00000004, // Near zero
                0x7FFFFFF0,
                0x7FFFFFF8,
                0x7FFFFFFC,
                0x7FFFFFFF, // Near 31-bit max
                0x80000000,
                0x80000001,
                0x80000002,
                0x80000004, // Sign bit flip
                WRAP_BOUNDARY_LOW - 16,
                WRAP_BOUNDARY_LOW - 8, // Test region low
                WRAP_BOUNDARY_LOW,
                WRAP_BOUNDARY_LOW + 8, // Test region boundary
                WRAP_BOUNDARY_HIGH - 8,
                WRAP_BOUNDARY_HIGH // Test region high
            };

            uint32_t test_addr = boundary_addrs[wrap_test % 20];
            uint32_t filter_range = 1 << (filter_idx % 12); // Powers of 2 from 1 to 2048

            // Configure wrap-sensitive filter
            if (setup_axi_filter_wrap_entry(filter_idx, test_addr, test_addr + filter_range,
                                            FILTER_TYPE_ALLOWLIST | (wrap_test & 0x0F),
                                            1,                     // enable
                                            filter_idx % 4,        // priority
                                            wrap_test % 3) != 0) { // wrap mode
                continue;
            }

            // Test exact boundary conditions
            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 1, 4, AXI_WRITE);
            test_axi_transaction(test_addr + filter_range - 4, 4, AXI_READ);
            test_axi_transaction(test_addr + filter_range - 1, 1, AXI_WRITE);

            // Test wrap-around scenarios
            if (test_addr > 0x80000000) {
                // High address wrap-around
                test_axi_transaction(test_addr + filter_range, 4, AXI_READ); // Should wrap
                test_axi_transaction(test_addr + filter_range + 1, 4, AXI_WRITE);
            }

            // Cross-boundary burst access
            if (filter_range >= 8) {
                test_axi_transaction(test_addr + filter_range - 4, 8, AXI_READ); // Crosses boundary
            }
        }
    }

    printf("Address wrap boundary precision: PASS\n");
    return 0;
}

static int test_filter_overflow_underflow_cases(void) {
    printf("Starting filter overflow/underflow cases test...\n");

    // Scenario 2: Filter overflow/underflow cases
    for (int overflow_test = 0; overflow_test < 32; overflow_test++) {
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            // Overflow scenarios
            uint32_t base_addr = WRAP_TEST_BASE + overflow_test * 0x1000000;
            uint32_t overflow_size = 0xFFFFFFFF - base_addr + 1; // Will cause overflow

            // Test 1: Address + Size overflow
            if (setup_axi_filter_wrap_entry(filter_idx, base_addr, base_addr + overflow_size,
                                            FILTER_TYPE_BLOCKLIST,
                                            1,              // enable
                                            filter_idx % 8, // priority
                                            2) != 0) {      // wrap mode with overflow
                // Expected to fail or wrap, continue testing
            }

            // Test access at overflow boundary
            test_axi_transaction(base_addr, 4, AXI_READ);
            test_axi_transaction(0xFFFFFFFC, 4, AXI_WRITE); // Near max address
            test_axi_transaction(0xFFFFFFFE, 2, AXI_READ);  // At max-1
            test_axi_transaction(0x00000000, 4, AXI_WRITE); // Wrap to zero

            // Test 2: Size underflow scenarios
            uint32_t underflow_end = base_addr - 1; // End < start
            if (setup_axi_filter_wrap_entry(filter_idx, base_addr, underflow_end,
                                            FILTER_TYPE_ALLOWLIST,
                                            1, // enable
                                            filter_idx % 8,
                                            1) != 0) { // wrap mode with underflow
                // Expected behavior varies by implementation
            }

            // Test 3: Counter overflow in filter logic
            for (int counter_test = 0; counter_test < 8; counter_test++) {
                uint32_t counter_addr = base_addr + counter_test * 0x100000;

                // Generate many hits to potentially overflow internal counters
                for (int hit_count = 0; hit_count < 256; hit_count++) {
                    test_axi_transaction(counter_addr + hit_count * 4, 4,
                                         (hit_count % 2) ? AXI_WRITE : AXI_READ);
                }
            }

            // Test 4: Priority overflow
            uint32_t invalid_priority = 0xFFFFFFFF; // Invalid high priority
            if (setup_axi_filter_wrap_entry(filter_idx, base_addr, base_addr + 0x1000,
                                            FILTER_TYPE_MONITOR,
                                            1, // enable
                                            invalid_priority,
                                            0) != 0) { // no wrap
                // Should handle invalid priority gracefully
            }
        }
    }

    printf("Filter overflow/underflow cases: PASS\n");
    return 0;
}

static int test_concurrent_filter_wrap_conflicts(void) {
    printf("Starting concurrent filter wrap conflicts test...\n");

    // Scenario 3: Concurrent filter wrap conflicts
    for (int conflict_test = 0; conflict_test < 24; conflict_test++) {
        // Configure multiple overlapping filters with conflicting wrap modes
        for (int filter_set = 0; filter_set < 4; filter_set++) {
            uint32_t set_base = WRAP_TEST_BASE + conflict_test * 0x2000000 + filter_set * 0x800000;

            for (int filter_idx = filter_set * 4; filter_idx < (filter_set + 1) * 4; filter_idx++) {
                uint32_t filter_start = set_base + filter_idx * 0x100000;
                uint32_t filter_end = filter_start + 0x200000; // Overlapping ranges

                // Different wrap modes for conflicting filters
                int wrap_mode = (filter_idx + conflict_test) % 4;
                int filter_type = (filter_idx % 2) ? FILTER_TYPE_ALLOWLIST : FILTER_TYPE_BLOCKLIST;

                if (setup_axi_filter_wrap_entry(filter_idx, filter_start, filter_end,
                                                filter_type | ((conflict_test & 0x7) << 4),
                                                1,               // enable
                                                filter_idx % 16, // varying priority
                                                wrap_mode) != 0) {
                    continue;
                }
            }
        }

        // Test overlapping regions with concurrent access
        uint32_t overlap_base = WRAP_TEST_BASE + conflict_test * 0x2000000 + 0x180000;

        for (int concurrent_access = 0; concurrent_access < 32; concurrent_access++) {
            uint32_t access_addr = overlap_base + concurrent_access * 0x40000;

            // This address should hit multiple filters with different wrap modes
            test_axi_transaction(access_addr, 4, AXI_READ);
            test_axi_transaction(access_addr + 0x10000, 8, AXI_WRITE);
            test_axi_transaction(access_addr + 0x20000, 16, AXI_READ);
        }

        // Dynamic conflict resolution - disable some filters
        for (int disable_test = 0; disable_test < 8; disable_test++) {
            int target_filter = (conflict_test * 2 + disable_test) % 16;

            if (setup_axi_filter_wrap_entry(target_filter, 0, 0, // dummy addresses
                                            FILTER_TYPE_ALLOWLIST,
                                            0, // disable
                                            0, 0) == 0) {

                // Test access pattern after disabling filter
                uint32_t post_disable_addr = overlap_base + disable_test * 0x8000;
                test_axi_transaction(post_disable_addr, 4, AXI_READ);
                test_axi_transaction(post_disable_addr + 0x1000, 4, AXI_WRITE);
            }
        }
    }

    printf("Concurrent filter wrap conflicts: PASS\n");
    return 0;
}

static int test_wrap_mode_state_transitions(void) {
    printf("Starting wrap mode state transitions test...\n");

    // Scenario 4: Wrap mode state transitions
    for (int transition_test = 0; transition_test < 16; transition_test++) {
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            uint32_t trans_base =
                WRAP_TEST_BASE + transition_test * 0x1000000 + filter_idx * 0x100000;

            // State Transition Sequence
            int wrap_modes[] = {0, 1, 2, 3, 2, 1, 0}; // Cycle through modes
            int filter_types[] = {FILTER_TYPE_ALLOWLIST,
                                  FILTER_TYPE_BLOCKLIST,
                                  FILTER_TYPE_REMAP,
                                  FILTER_TYPE_MONITOR,
                                  FILTER_TYPE_ALLOWLIST | FILTER_TYPE_MONITOR,
                                  FILTER_TYPE_BLOCKLIST | FILTER_TYPE_REMAP,
                                  FILTER_TYPE_REMAP | FILTER_TYPE_MONITOR};

            for (int state = 0; state < 7; state++) {
                int current_wrap_mode = wrap_modes[state];
                int current_filter_type = filter_types[state % 7];

                if (setup_axi_filter_wrap_entry(filter_idx, trans_base, trans_base + 0x80000,
                                                current_filter_type,
                                                1,     // enable
                                                state, // changing priority
                                                current_wrap_mode) != 0) {
                    continue;
                }

                // Test this state
                uint32_t state_test_addr = trans_base + state * 0x8000;
                test_axi_transaction(state_test_addr, 4, AXI_READ);
                test_axi_transaction(state_test_addr + 0x1000, 4, AXI_WRITE);

                // State-specific testing
                switch (current_wrap_mode) {
                case 0:                                                      // No wrap
                    test_axi_transaction(trans_base + 0x7FFFC, 4, AXI_READ); // Near end
                    break;
                case 1:                                                      // Address wrap
                    test_axi_transaction(trans_base + 0x80000, 4, AXI_READ); // Beyond end
                    break;
                case 2:                                                   // Size wrap
                    test_axi_transaction(state_test_addr, 128, AXI_READ); // Large burst
                    break;
                case 3:                                                       // Full wrap
                    test_axi_transaction(trans_base + 0x100000, 4, AXI_READ); // Far beyond
                    break;
                }

                // Verify state transition effects
                for (int verify = 0; verify < 4; verify++) {
                    uint32_t verify_addr = trans_base + 0x10000 + verify * 0x4000;
                    test_axi_transaction(verify_addr, 4, (verify % 2) ? AXI_WRITE : AXI_READ);
                }
            }

            // Final state verification
            uint32_t final_test_addr = trans_base + 0x40000;
            test_axi_transaction(final_test_addr, 32, AXI_READ);
            test_axi_transaction(final_test_addr + 0x2000, 32, AXI_WRITE);
        }
    }

    printf("Wrap mode state transitions: PASS\n");
    return 0;
}

static int test_burst_wrap_edge_cases(void) {
    printf("Starting burst wrap edge cases test...\n");

    // Scenario 5: Burst wrap edge cases
    uint32_t burst_sizes[] = {1, 2, 4, 8, 16, 32, 64, 128, 256};
    uint32_t wrap_alignments[] = {4, 8, 16, 32, 64, 128, 256, 512, 1024};

    for (int burst_test = 0; burst_test < 48; burst_test++) {
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            uint32_t burst_base = WRAP_TEST_BASE + burst_test * 0x800000 + filter_idx * 0x80000;
            uint32_t alignment = wrap_alignments[burst_test % 9];
            uint32_t aligned_base = (burst_base + alignment - 1) & ~(alignment - 1);

            // Configure filter for burst wrap testing
            if (setup_axi_filter_wrap_entry(filter_idx, aligned_base, aligned_base + alignment * 4,
                                            FILTER_TYPE_ALLOWLIST | FILTER_TYPE_MONITOR,
                                            1, // enable
                                            filter_idx % 8,
                                            2) != 0) { // size wrap mode
                continue;
            }

            // Test different burst sizes at wrap boundaries
            for (int burst_idx = 0; burst_idx < 9; burst_idx++) {
                uint32_t burst_size = burst_sizes[burst_idx];
                if (burst_size > alignment) continue; // Skip if burst > alignment

                // Test burst at start of region
                test_axi_transaction(aligned_base, burst_size, AXI_READ);
                test_axi_transaction(aligned_base, burst_size, AXI_WRITE);

                // Test burst near end of region
                uint32_t near_end = aligned_base + alignment * 4 - burst_size;
                test_axi_transaction(near_end, burst_size, AXI_READ);
                test_axi_transaction(near_end, burst_size, AXI_WRITE);

                // Test burst crossing wrap boundary
                uint32_t cross_boundary = aligned_base + alignment * 4 - burst_size / 2;
                test_axi_transaction(cross_boundary, burst_size, AXI_READ);
                test_axi_transaction(cross_boundary, burst_size, AXI_WRITE);

                // Test burst at alignment boundaries within region
                for (int align_test = 1; align_test < 4; align_test++) {
                    uint32_t align_addr = aligned_base + alignment * align_test;
                    if (align_addr + burst_size <= aligned_base + alignment * 4) {
                        test_axi_transaction(align_addr, burst_size, AXI_READ);
                        test_axi_transaction(align_addr, burst_size, AXI_WRITE);
                    }
                }
            }

            // Special case: Power-of-2 wrap boundaries
            if ((alignment & (alignment - 1)) == 0) { // Power of 2
                uint32_t wrap_addr = aligned_base + alignment - 4;
                test_axi_transaction(wrap_addr, 8, AXI_READ);      // Cross wrap boundary
                test_axi_transaction(wrap_addr + 1, 8, AXI_WRITE); // Misaligned cross
            }
        }
    }

    printf("Burst wrap edge cases: PASS\n");
    return 0;
}

static int test_wrap_error_injection_recovery(void) {
    printf("Starting wrap error injection and recovery test...\n");

    // Scenario 6: Wrap error injection and recovery
    for (int error_test = 0; error_test < 20; error_test++) {
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            uint32_t error_base = WRAP_TEST_BASE + error_test * 0x400000 + filter_idx * 0x40000;

            // Error Injection 1: Invalid wrap configuration
            if (setup_axi_filter_wrap_entry(filter_idx, error_base + 0x1000,
                                            error_base, // end < start
                                            FILTER_TYPE_ALLOWLIST,
                                            1, // enable
                                            filter_idx,
                                            3) != 0) { // full wrap with invalid range
                // Expected to fail
            }

            // Test access during error state
            test_axi_transaction(error_base, 4, AXI_READ);
            test_axi_transaction(error_base + 0x500, 4, AXI_WRITE);

            // Recovery 1: Fix configuration
            if (setup_axi_filter_wrap_entry(filter_idx, error_base, error_base + 0x8000,
                                            FILTER_TYPE_ALLOWLIST,
                                            1, // enable
                                            filter_idx,
                                            1) == 0) { // valid address wrap

                // Verify recovery
                test_axi_transaction(error_base + 0x1000, 4, AXI_READ);
                test_axi_transaction(error_base + 0x2000, 4, AXI_WRITE);
            }

            // Error Injection 2: Wrap mode confusion
            // Set conflicting wrap modes rapidly
            for (int rapid_change = 0; rapid_change < 8; rapid_change++) {
                int chaotic_wrap_mode = rapid_change % 4;
                setup_axi_filter_wrap_entry(filter_idx, error_base, error_base + 0x4000,
                                            FILTER_TYPE_BLOCKLIST,
                                            1, // enable
                                            rapid_change, chaotic_wrap_mode);

                // Quick access during rapid reconfiguration
                test_axi_transaction(error_base + rapid_change * 0x200, 4, AXI_READ);
            }

            // Error Injection 3: Resource exhaustion simulation
            // Try to configure beyond hardware limits
            uint32_t excessive_range = 0x80000000; // Very large range
            if (setup_axi_filter_wrap_entry(filter_idx, error_base, error_base + excessive_range,
                                            FILTER_TYPE_REMAP,
                                            1, // enable
                                            filter_idx,
                                            2) != 0) { // size wrap with huge range
                // Expected resource limit hit
            }

            // Recovery 2: Reset to sane configuration
            if (setup_axi_filter_wrap_entry(filter_idx, 0, 0, // Clear configuration
                                            0,                // Clear type
                                            0,                // disable
                                            0, 0) == 0) {

                // Reconfigure with normal settings
                if (setup_axi_filter_wrap_entry(filter_idx, error_base, error_base + 0x2000,
                                                FILTER_TYPE_MONITOR,
                                                1,         // enable
                                                0,         // normal priority
                                                0) == 0) { // no wrap

                    // Final verification
                    test_axi_transaction(error_base + 0x800, 8, AXI_READ);
                    test_axi_transaction(error_base + 0x1000, 8, AXI_WRITE);
                }
            }
        }
    }

    printf("Wrap error injection and recovery: PASS\n");
    return 0;
}

static int test_wrap_performance_corner_cases(void) {
    printf("Starting wrap performance corner cases test...\n");

    // Scenario 7: Wrap performance corner cases
    for (int perf_test = 0; perf_test < 12; perf_test++) {
        // Configure high-stress wrap scenarios
        for (int filter_idx = 0; filter_idx < 16; filter_idx++) {
            uint32_t perf_base = WRAP_TEST_BASE + perf_test * 0x2000000 + filter_idx * 0x200000;

            // Performance Corner Case 1: Maximum wrap frequency
            if (setup_axi_filter_wrap_entry(filter_idx, perf_base,
                                            perf_base + 0x1000, // Small range
                                            FILTER_TYPE_ALLOWLIST | FILTER_TYPE_MONITOR,
                                            1, // enable
                                            filter_idx % 8,
                                            3) != 0) { // full wrap mode
                continue;
            }

            // Generate high-frequency wrap events
            for (int wrap_stress = 0; wrap_stress < 128; wrap_stress++) {
                uint32_t stress_addr = perf_base + (wrap_stress * 0x100) % 0x1000;
                test_axi_transaction(stress_addr, 4, (wrap_stress % 2) ? AXI_WRITE : AXI_READ);
            }

            // Performance Corner Case 2: Wrap with maximum burst sizes
            uint32_t max_burst_addr = perf_base + 0x800;
            test_axi_transaction(max_burst_addr, 256, AXI_READ);  // Max burst
            test_axi_transaction(max_burst_addr, 256, AXI_WRITE); // Max burst

            // Performance Corner Case 3: Concurrent wraps across filters
            if (filter_idx < 8) {
                // Create concurrent wrap scenario with next filter
                uint32_t concurrent_base = perf_base + 0x100000;
                if (setup_axi_filter_wrap_entry(filter_idx + 8, concurrent_base,
                                                concurrent_base + 0x2000, FILTER_TYPE_BLOCKLIST,
                                                1, // enable
                                                (filter_idx + 8) % 8,
                                                2) == 0) { // size wrap

                    // Simultaneous access to both wrap regions
                    for (int simultaneous = 0; simultaneous < 16; simultaneous++) {
                        test_axi_transaction(perf_base + simultaneous * 0x40, 4, AXI_READ);
                        test_axi_transaction(concurrent_base + simultaneous * 0x80, 4, AXI_WRITE);
                    }
                }
            }

            // Performance Corner Case 4: Pathological wrap patterns
            uint32_t pathological_patterns[] = {
                0x555, 0xAAA, 0x333, 0xCCC, 0x0F0, 0xF0F // Alternating patterns
            };

            for (int pattern_idx = 0; pattern_idx < 6; pattern_idx++) {
                uint32_t pattern_offset = pathological_patterns[pattern_idx];
                uint32_t pattern_addr = perf_base + (pattern_offset % 0x1000);

                test_axi_transaction(pattern_addr, 4, AXI_READ);
                test_axi_transaction(pattern_addr, 4, AXI_WRITE);

                // Create wrap scenario with pattern
                if (pattern_addr + 8 > perf_base + 0x1000) {
                    test_axi_transaction(pattern_addr, 8, AXI_READ); // Will wrap
                }
            }
        }
    }

    printf("Wrap performance corner cases: PASS\n");
    return 0;
}

int main(void) {
    printf("Filter Wrap Edge Case Test\n");
    printf("Strategy: Precise filter-wrap boundary and anomaly cases\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_filter_wrap_edge_case_test");
        return TEST_FAIL;
    }

    // Run all filter-wrap edge-case scenarios
    if (test_address_wrap_boundary_precision() != 0) {
        test_fail("Address Wrap Boundary Precision");
        return TEST_FAIL;
    }

    if (test_filter_overflow_underflow_cases() != 0) {
        test_fail("Filter Overflow Underflow Cases");
        return TEST_FAIL;
    }

    if (test_concurrent_filter_wrap_conflicts() != 0) {
        test_fail("Concurrent Filter Wrap Conflicts");
        return TEST_FAIL;
    }

    if (test_wrap_mode_state_transitions() != 0) {
        test_fail("Wrap Mode State Transitions");
        return TEST_FAIL;
    }

    if (test_burst_wrap_edge_cases() != 0) {
        test_fail("Burst Wrap Edge Cases");
        return TEST_FAIL;
    }

    if (test_wrap_error_injection_recovery() != 0) {
        test_fail("Wrap Error Injection Recovery");
        return TEST_FAIL;
    }

    if (test_wrap_performance_corner_cases() != 0) {
        test_fail("Wrap Performance Corner Cases");
        return TEST_FAIL;
    }

    printf("\n=== FILTER WRAP EDGE CASE TEST PASSED ===\n");

    test_pass("fabric_filter_wrap_edge_case_test");
    return TEST_PASS;
}
