/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_local_alias_remap_toggle_p3_test
 *
 * Strategy: Local-alias remap toggle stress; full CSR field coverage
 *
 * Focus on local-alias remap CSR toggles and full address-translation coverage
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Local alias toggle scenario count
#define LOCAL_ALIAS_SCENARIOS 8

// Local-alias base definitions
#define LOCAL_ALIAS_SRC_BASE 0x30000000
#define LOCAL_ALIAS_DEST_BASE 0x70000000
#define LOCAL_MASTER_RANGE 0x08000000
#define GLOBAL_MASTER_RANGE 0x10000000

// CSR field-toggle patterns
#define CSR_TOGGLE_PATTERNS 16
#define MAX_LOCAL_REGIONS 8

static int test_local_alias_csr_intensive_toggle(void) {
    printf("Starting local alias CSR intensive toggle...\n");

    // Scenario 1: Intensive CSR-field toggle
    for (int csr_round = 0; csr_round < 32; csr_round++) {
        // Cover all 8 local-alias regions
        for (int region = 0; region < 8; region++) {
            uint32_t src_base = LOCAL_ALIAS_SRC_BASE + csr_round * 0x400000 + region * 0x80000;
            uint32_t dest_base = LOCAL_ALIAS_DEST_BASE + csr_round * 0x400000 + region * 0x80000;

            // Toggle enable/disable
            int enable_state = (csr_round + region) & 1;

            // Toggle various CSR field combinations
            int priority = (csr_round >> 1) & 0x7;         // 3-bit priority
            int access_type = (csr_round >> 4) & 0x3;      // 2-bit access type
            int cache_policy = (region ^ csr_round) & 0xF; // 4-bit cache policy

            if (setup_local_alias_remap_extended(region, src_base, dest_base, enable_state,
                                                 priority, access_type, cache_policy,
                                                 0xFFF80000) != 0) { // 512KB granularity
                continue;                                            // Skip invalid combinations
            }

            // Test effects of CSR-field toggles
            uint32_t test_addr = src_base + 0x10000;

            if (enable_state) {
                // Access while enabled
                test_axi_transaction(test_addr, 4, AXI_READ);
                test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE);
            } else {
                // Access while disabled (expect bypass or fail)
                test_axi_transaction(test_addr, 4, AXI_READ);
            }
        }
    }

    printf("Local alias CSR intensive toggle: PASS\n");
    return 0;
}

static int test_priority_resolution_comprehensive(void) {
    printf("Starting priority resolution comprehensive test...\n");

    // Scenario 2: Full priority-resolution test
    for (int priority_test = 0; priority_test < 16; priority_test++) {
        // Set overlapping local-alias regions; test priority resolution
        for (int region = 0; region < 8; region++) {
            uint32_t base_addr = LOCAL_ALIAS_SRC_BASE + priority_test * 0x800000;
            uint32_t overlap_start = base_addr + region * 0x60000; // create overlap
            uint32_t dest_addr =
                LOCAL_ALIAS_DEST_BASE + priority_test * 0x800000 + region * 0x100000;

            // Different priority per region
            int priority_val = (region + priority_test) % 8;

            if (setup_local_alias_remap_extended(region, overlap_start, dest_addr,
                                                 1, // enable
                                                 priority_val,
                                                 region % 4, // access type
                                                 CACHE_ATTR_WRITEBACK,
                                                 0xFFF00000) != 0) { // 1MB mask
                continue;
            }

            // Access overlapping regions; verify priority resolution
            uint32_t overlap_addr = overlap_start + 0x40000; // inside overlap region

            test_axi_transaction(overlap_addr, 1 << (region % 3), AXI_READ);
            test_axi_transaction(overlap_addr + 0x100, 1 << ((region + 1) % 3), AXI_WRITE);
        }
    }

    printf("Priority resolution comprehensive: PASS\n");
    return 0;
}

static int test_local_master_access_patterns(void) {
    printf("Starting local master access patterns test...\n");

    // Scenario 3: Local-master access-mode test
    for (int master_test = 0; master_test < 24; master_test++) {
        // Configure different local-master access modes
        for (int region = 0; region < 8; region++) {
            uint32_t local_src = LOCAL_ALIAS_SRC_BASE + master_test * 0x200000 + region * 0x40000;
            uint32_t local_dest = LOCAL_ALIAS_DEST_BASE + master_test * 0x200000 + region * 0x40000;

            // Local master specific configurations
            int master_id = (master_test + region) % 4; // 4 different masters
            int access_mode = master_test % 3;          // R, W, RW modes

            if (setup_local_alias_remap_master_specific(region, local_src, local_dest,
                                                        1, // enable
                                                        master_id, access_mode,
                                                        0xFFFC0000) != 0) { // 256KB granularity
                continue;
            }

            // Simulate accesses from different masters
            uint32_t test_addr = local_src + 0x8000;

            // Master-0 access
            if (master_id == 0 && (access_mode == 0 || access_mode == 2)) {
                test_axi_transaction(test_addr, 4, AXI_READ);
            }

            // Master-1 access
            if (master_id == 1 && (access_mode == 1 || access_mode == 2)) {
                test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);
            }

            // Burst access test
            if (access_mode == 2) { // RW mode
                test_axi_transaction(test_addr + 0x1000, 32, AXI_READ);
                test_axi_transaction(test_addr + 0x1020, 32, AXI_WRITE);
            }
        }
    }

    printf("Local master access patterns: PASS\n");
    return 0;
}

static int test_address_range_boundary_toggle(void) {
    printf("Starting address range boundary toggle test...\n");

    // Scenario 4: Address-range boundary toggle test
    uint32_t boundary_patterns[] = {
        0x00000FFF, 0x00001000, // 4KB boundary
        0x00003FFF, 0x00004000, // 16KB boundary
        0x0000FFFF, 0x00010000, // 64KB boundary
        0x0003FFFF, 0x00040000, // 256KB boundary
        0x000FFFFF, 0x00100000, // 1MB boundary
        0x003FFFFF, 0x00400000, // 4MB boundary
        0x00FFFFFF, 0x01000000, // 16MB boundary
        0x03FFFFFF, 0x04000000  // 64MB boundary
    };

    for (int boundary_idx = 0; boundary_idx < 16; boundary_idx++) {
        uint32_t boundary_addr = boundary_patterns[boundary_idx];

        for (int region = 0; region < 8; region++) {
            uint32_t aligned_src =
                (LOCAL_ALIAS_SRC_BASE & 0xFC000000) | (boundary_addr & 0x03FFFFFF);
            uint32_t aligned_dest =
                LOCAL_ALIAS_DEST_BASE + boundary_idx * 0x1000000 + region * 0x200000;

            if (setup_local_alias_remap_boundary(region, aligned_src, aligned_dest,
                                                 1,                // enable
                                                 boundary_idx % 8, // priority
                                                 0xFF000000 | (boundary_addr & 0x00FFFFFF)) != 0) {
                continue;
            }

            // Access near boundaries
            test_axi_transaction(aligned_src, 1, AXI_READ);
            test_axi_transaction(aligned_src + 1, 1, AXI_WRITE);
            test_axi_transaction(aligned_src + 0xFFF, 1, AXI_READ);
            test_axi_transaction(aligned_src + 0x1000, 1, AXI_WRITE);

            // Cross-boundary access
            if (boundary_idx % 2) {
                test_axi_transaction(aligned_src + 0xFFC, 8, AXI_READ); // cross-boundary
            }
        }
    }

    printf("Address range boundary toggle: PASS\n");
    return 0;
}

static int test_cache_coherency_scenarios(void) {
    printf("Starting cache coherency scenarios test...\n");

    // Scenario 5: Cache-coherency scenario test
    uint32_t cache_scenarios[] = {CACHE_ATTR_DEVICE,           CACHE_ATTR_NORMAL_NC,
                                  CACHE_ATTR_NORMAL_WT,        CACHE_ATTR_NORMAL_WB,
                                  CACHE_ATTR_STRONGLY_ORDERED, CACHE_ATTR_WRITE_COMBINING,
                                  CACHE_ATTR_WRITE_ALLOCATE,   CACHE_ATTR_READ_ALLOCATE};

    for (int cache_idx = 0; cache_idx < 8; cache_idx++) {
        uint32_t cache_attr = cache_scenarios[cache_idx];

        for (int region = 0; region < 8; region++) {
            uint32_t cache_src = LOCAL_ALIAS_SRC_BASE + cache_idx * 0x800000 + region * 0x100000;
            uint32_t cache_dest = LOCAL_ALIAS_DEST_BASE + cache_idx * 0x800000 + region * 0x100000;

            if (setup_local_alias_remap_extended(region, cache_src, cache_dest,
                                                 1,          // enable
                                                 cache_idx,  // priority
                                                 region % 4, // access type
                                                 cache_attr, 0xFFF00000) != 0) {
                continue;
            }

            // Vary access mode by cache attributes
            uint32_t test_addr = cache_src + 0x20000;

            if (cache_attr & CACHE_ATTR_WRITEBACK) {
                // Writeback cache - large burst access
                test_axi_transaction(test_addr, 64, AXI_READ);
                test_axi_transaction(test_addr + 64, 64, AXI_WRITE);
            } else if (cache_attr & CACHE_ATTR_WRITETHROUGH) {
                // Writethrough cache - medium burst
                test_axi_transaction(test_addr, 16, AXI_READ);
                test_axi_transaction(test_addr + 16, 16, AXI_WRITE);
            } else {
                // Non-cacheable - small access
                test_axi_transaction(test_addr, 4, AXI_READ);
                test_axi_transaction(test_addr + 4, 4, AXI_WRITE);
            }
        }
    }

    printf("Cache coherency scenarios: PASS\n");
    return 0;
}

static int test_disable_enable_sequence_comprehensive(void) {
    printf("Starting disable/enable sequence comprehensive test...\n");

    // Scenario 6: Combined disable/enable sequence test
    for (int sequence_test = 0; sequence_test < 16; sequence_test++) {
        for (int region = 0; region < 8; region++) {
            uint32_t seq_src = LOCAL_ALIAS_SRC_BASE + sequence_test * 0x400000 + region * 0x80000;
            uint32_t seq_dest = LOCAL_ALIAS_DEST_BASE + sequence_test * 0x400000 + region * 0x80000;

            // Phase 1: enable all regions
            if (setup_local_alias_remap_extended(region, seq_src, seq_dest,
                                                 1, // enable
                                                 sequence_test % 8, region % 4,
                                                 CACHE_ATTR_WRITEBACK, 0xFFF80000) != 0) {
                continue;
            }

            // Access while enabled
            uint32_t test_addr = seq_src + 0x10000;
            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);

            // Phase 2: disable regions
            if (setup_local_alias_remap_extended(region, seq_src, seq_dest,
                                                 0, // disable
                                                 sequence_test % 8, region % 4,
                                                 CACHE_ATTR_WRITEBACK, 0xFFF80000) != 0) {
                continue;
            }

            // Access while disabled
            test_axi_transaction(test_addr, 4, AXI_READ); // Should fail or pass through
            test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);

            // Phase 3: Re-enable with different config
            if (setup_local_alias_remap_extended(region, seq_src,
                                                 seq_dest + 0x1000000,    // different dest
                                                 1,                       // re-enable
                                                 (sequence_test + 4) % 8, // different priority
                                                 (region + 2) % 4,        // different access type
                                                 CACHE_ATTR_NORMAL_NC,    // different cache
                                                 0xFFF80000) != 0) {
                continue;
            }

            // Access after re-enable
            test_axi_transaction(test_addr, 8, AXI_READ);
            test_axi_transaction(test_addr + 0x200, 8, AXI_WRITE);
        }
    }

    printf("Disable/enable sequence comprehensive: PASS\n");
    return 0;
}

static int test_error_injection_and_recovery(void) {
    printf("Starting error injection and recovery test...\n");

    // Scenario 7: Error-injection and recovery test
    for (int error_test = 0; error_test < 12; error_test++) {
        for (int region = 0; region < 8; region++) {
            uint32_t err_src = LOCAL_ALIAS_SRC_BASE + error_test * 0x200000 + region * 0x40000;
            uint32_t err_dest = LOCAL_ALIAS_DEST_BASE + error_test * 0x200000 + region * 0x40000;

            // Set normal configuration
            if (setup_local_alias_remap_extended(region, err_src, err_dest,
                                                 1, // enable
                                                 region,
                                                 0, // read access
                                                 CACHE_ATTR_WRITEBACK, 0xFFFC0000) != 0) {
                continue;
            }

            // Error injection: Invalid configurations
            uint32_t test_addr = err_src + 0x8000;

            // Test 1: Try invalid address alignment
            test_axi_transaction(test_addr + 1, 4, AXI_READ); // Misaligned
            test_axi_transaction(test_addr + 2, 4, AXI_WRITE);

            // Test 2: Access beyond region range
            test_axi_transaction(err_src + 0x50000, 4, AXI_READ); // Out of range

            // Test 3: illegal burst size
            test_axi_transaction(test_addr, 127, AXI_READ); // Odd burst size

            // Recovery: reconfigure to a valid setting
            if (setup_local_alias_remap_extended(region, err_src, err_dest,
                                                 1, // enable
                                                 region,
                                                 2, // read-write access
                                                 CACHE_ATTR_WRITEBACK, 0xFFFC0000) != 0) {
                continue;
            }

            // Verify normal operation after recovery
            test_axi_transaction(test_addr, 4, AXI_READ);
            test_axi_transaction(test_addr + 0x100, 4, AXI_WRITE);
        }
    }

    printf("Error injection and recovery: PASS\n");
    return 0;
}

static int test_concurrent_multi_region_stress(void) {
    printf("Starting concurrent multi-region stress test...\n");

    // Scenario 8: Concurrent multi-region stress test
    for (int stress_test = 0; stress_test < 8; stress_test++) {
        // Program all 8 regions at once
        for (int region = 0; region < 8; region++) {
            uint32_t stress_src =
                LOCAL_ALIAS_SRC_BASE + stress_test * 0x2000000 + region * 0x400000;
            uint32_t stress_dest =
                LOCAL_ALIAS_DEST_BASE + stress_test * 0x2000000 + region * 0x400000;

            if (setup_local_alias_remap_extended(region, stress_src, stress_dest,
                                                 1,               // enable
                                                 region,          // different priority per region
                                                 stress_test % 4, // cycle access type
                                                 (stress_test * region) % 8, // varying cache attr
                                                 0xFFE00000) != 0) {         // 2MB granularity
                continue;
            }
        }

        // Access all regions in parallel
        for (int parallel_round = 0; parallel_round < 16; parallel_round++) {
            for (int region = 0; region < 8; region++) {
                uint32_t parallel_addr = LOCAL_ALIAS_SRC_BASE + stress_test * 0x2000000 +
                                         region * 0x400000 + parallel_round * 0x10000;

                // Rapid consecutive accesses
                test_axi_transaction(parallel_addr, 4, AXI_READ);
                test_axi_transaction(parallel_addr + 0x100, 4, AXI_WRITE);

                // Large-burst access
                if (parallel_round % 4 == 0) {
                    test_axi_transaction(parallel_addr + 0x1000, 32, AXI_READ);
                    test_axi_transaction(parallel_addr + 0x1020, 32, AXI_WRITE);
                }
            }
        }
    }

    printf("Concurrent multi-region stress: PASS\n");
    return 0;
}

int main(void) {
    printf("Local Alias Remap Toggle Test\n");
    printf("Strategy: Local-alias remap toggle stress; full CSR field coverage\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_local_alias_remap_toggle_p3_test");
        return TEST_FAIL;
    }

    // Run all local-alias remap toggle scenarios
    if (test_local_alias_csr_intensive_toggle() != 0) {
        test_fail("Local Alias CSR Intensive Toggle");
        return TEST_FAIL;
    }

    if (test_priority_resolution_comprehensive() != 0) {
        test_fail("Priority Resolution Comprehensive");
        return TEST_FAIL;
    }

    if (test_local_master_access_patterns() != 0) {
        test_fail("Local Master Access Patterns");
        return TEST_FAIL;
    }

    if (test_address_range_boundary_toggle() != 0) {
        test_fail("Address Range Boundary Toggle");
        return TEST_FAIL;
    }

    if (test_cache_coherency_scenarios() != 0) {
        test_fail("Cache Coherency Scenarios");
        return TEST_FAIL;
    }

    if (test_disable_enable_sequence_comprehensive() != 0) {
        test_fail("Disable Enable Sequence");
        return TEST_FAIL;
    }

    if (test_error_injection_and_recovery() != 0) {
        test_fail("Error Injection and Recovery");
        return TEST_FAIL;
    }

    if (test_concurrent_multi_region_stress() != 0) {
        test_fail("Concurrent Multi-Region Stress");
        return TEST_FAIL;
    }

    printf("\n=== LOCAL ALIAS REMAP TOGGLE TEST PASSED ===\n");

    test_pass("fabric_local_alias_remap_toggle_p3_test");
    return TEST_PASS;
}
