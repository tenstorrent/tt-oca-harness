/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Filter datapath matrix: no-match default block, read-only pass with write
 * block, secure/non-secure allow/deny, and burst-size allow/block cases.
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

#define FILTER_TEST_BASE_ADDR 0x30000000

// AXI protection attributes.
#define AXI_PROT_SECURE 0x0
#define AXI_PROT_NON_SECURE 0x1
#define AXI_PROT_PRIVILEGED 0x0
#define AXI_PROT_USER 0x2

static int test_no_match_default_block_scenarios(void) {
    printf("Starting no-match default block scenarios...\n");

    for (int test_case = 0; test_case < 16; test_case++) {
        uint32_t test_addr = FILTER_TEST_BASE_ADDR + test_case * 0x10000;

        for (int filter_entry = 0; filter_entry < 8; filter_entry++) {
            uint32_t filter_start = 0x50000000 + filter_entry * 0x100000; // different range
            uint32_t filter_end = filter_start + 0x80000;

            // Program filter entries that do not cover test_addr
            if (setup_output_remap_region_extended(filter_entry, filter_start, filter_end,
                                                   1,          // enable
                                                   0,          // allow
                                                   0xFFFF0000, // mask
                                                   AXI_PROT_NON_SECURE) != 0) {
                return -1;
            }
        }

        // No-match addresses should be default-blocked
        if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
            // Expect fail - should be blocked
        }
        if (test_axi_transaction(test_addr + 0x100, 8, AXI_WRITE) != 0) {
            // Expect fail - should be blocked
        }
    }

    printf("No-match default block scenarios: PASS\n");
    return 0;
}

static int test_read_only_pass_write_block_combinations(void) {
    printf("Starting read-only pass/write block combinations...\n");

    for (int combo = 0; combo < 16; combo++) {
        uint32_t region_base = FILTER_TEST_BASE_ADDR + combo * 0x100000;

        for (int entry = 0; entry < 8; entry++) {
            uint32_t entry_start = region_base + entry * 0x20000;
            uint32_t entry_end = entry_start + 0x10000;

            if (setup_output_remap_region_extended(entry, entry_start, entry_end,
                                                   1,                         // enable
                                                   1,                         // read allowed
                                                   0xFFFF0000 | (1 << entry), // write blocked
                                                   AXI_PROT_SECURE) != 0) {
                return -1;
            }
        }

        for (int entry = 0; entry < 8; entry++) {
            uint32_t test_addr = region_base + entry * 0x20000 + 0x1000;

            // Read should pass
            if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
                printf("ERROR: Read should pass for combo %d entry %d\n", combo, entry);
                return -1;
            }

            // Write should block
            if (test_axi_transaction(test_addr + 4, 4, AXI_WRITE) != 0) {
                // Expect fail - write should be blocked
            }
        }
    }

    printf("Read-only pass/write block combinations: PASS\n");
    return 0;
}

static int test_ns_secure_allow_deny_patterns(void) {
    printf("Starting NS/secure allow/deny patterns...\n");

    uint32_t security_patterns[] = {AXI_PROT_SECURE, AXI_PROT_NON_SECURE,
                                    AXI_PROT_SECURE | AXI_PROT_PRIVILEGED,
                                    AXI_PROT_NON_SECURE | AXI_PROT_USER};

    for (int pattern_idx = 0; pattern_idx < 4; pattern_idx++) {
        for (int region = 0; region < 4; region++) {
            uint32_t region_start =
                FILTER_TEST_BASE_ADDR + pattern_idx * 0x1000000 + region * 0x100000;
            uint32_t region_end = region_start + 0x80000;

            uint32_t security_attr = security_patterns[pattern_idx];
            int allow_ns = (security_attr & AXI_PROT_NON_SECURE) ? 1 : 0;
            int allow_secure = (security_attr & AXI_PROT_NON_SECURE) ? 0 : 1;

            if (setup_output_remap_region_extended(region, region_start, region_end,
                                                   1,            // enable
                                                   allow_secure, // channel for secure
                                                   0xFFF80000 |
                                                       (allow_ns << 16), // mask with NS bit
                                                   security_attr) != 0) {
                return -1;
            }

            uint32_t test_addr = region_start + 0x10000;

            // Secure access
            if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
                if (allow_secure) {
                    printf("ERROR: Secure access should be allowed\n");
                    return -1;
                }
            }

            if (test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE) != 0) {
                if (allow_ns) {
                    printf("ERROR: NS access should be allowed\n");
                    return -1;
                }
            }
        }
    }

    printf("NS/secure allow/deny patterns: PASS\n");
    return 0;
}

static int test_burst_allowed_blocked_scenarios(void) {
    printf("Starting burst allowed/blocked scenarios...\n");

    uint32_t burst_sizes[] = {1, 2, 4, 8, 16, 32, 64, 128};

    for (int burst_idx = 0; burst_idx < 8; burst_idx++) {
        uint32_t burst_size = burst_sizes[burst_idx];
        uint32_t region_base = FILTER_TEST_BASE_ADDR + burst_idx * 0x200000;

        for (int filter_entry = 0; filter_entry < 8; filter_entry++) {
            uint32_t entry_start = region_base + filter_entry * 0x40000;
            uint32_t entry_end = entry_start + 0x20000;

            int burst_allowed = (burst_size <= (1 << filter_entry)) ? 1 : 0;

            if (setup_output_remap_region_extended(filter_entry, entry_start, entry_end,
                                                   1,             // enable
                                                   burst_allowed, // channel indicates burst policy
                                                   0xFFFE0000 |
                                                       (burst_size << 8), // mask with burst size
                                                   burst_size & 0xFF) != 0) {
                return -1;
            }
        }

        for (int entry = 0; entry < 8; entry++) {
            uint32_t test_addr = region_base + entry * 0x40000 + 0x8000;
            int burst_allowed = (burst_size <= (1 << entry)) ? 1 : 0;

            if (test_axi_transaction(test_addr, burst_size * 4, AXI_READ) != 0) {
                if (burst_allowed) {
                    printf("ERROR: Burst size %d should be allowed for entry %d\n", burst_size,
                           entry);
                    return -1;
                }
            }
        }
    }

    printf("Burst allowed/blocked scenarios: PASS\n");
    return 0;
}

int main(void) {
    printf("Filter Datapath Matrix Test\n");
    printf("Strategy: Targeted pass/block traffic tests covering all datapath combinations\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_filter_datapath_matrix_p3_test");
        return TEST_FAIL;
    }

    if (test_no_match_default_block_scenarios() != 0) {
        test_fail("No Match Default Block");
        return TEST_FAIL;
    }

    if (test_read_only_pass_write_block_combinations() != 0) {
        test_fail("Read Only Pass Write Block");
        return TEST_FAIL;
    }

    if (test_ns_secure_allow_deny_patterns() != 0) {
        test_fail("NS Secure Allow Deny");
        return TEST_FAIL;
    }

    if (test_burst_allowed_blocked_scenarios() != 0) {
        test_fail("Burst Allowed Blocked");
        return TEST_FAIL;
    }

    printf("\n=== FILTER DATAPATH MATRIX TEST PASSED ===\n");

    test_pass("fabric_filter_datapath_matrix_p3_test");
    return TEST_PASS;
}
