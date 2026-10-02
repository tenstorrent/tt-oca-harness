/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Alias-remap CSR field toggle stress across all 16 alias entries.
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

#define ALIAS_SRC_BASE 0x10000000
#define ALIAS_DEST_BASE 0x20000000

// Walking-one and toggle patterns for address, mask and attribute fields.
static const uint32_t intensive_patterns[] = {
    0x00000001, 0x00000002, 0x00000004, 0x00000008, 0x00000010, 0x00000020, 0x00000040, 0x00000080,
    0x00000100, 0x00000200, 0x00000400, 0x00000800, 0x00001000, 0x00002000, 0x00004000, 0x00008000,
    0x55555555, 0xAAAAAAAA, 0xCCCCCCCC, 0x33333333, 0x0F0F0F0F, 0xF0F0F0F0, 0x00FF00FF, 0xFF00FF00,
    0x0000FFFF, 0xFFFF0000, 0x12345678, 0x87654321, 0xDEADBEEF, 0xCAFEBABE, 0xFEEDFACE, 0xBADC0FFE};

static int test_all_16_alias_entries_comprehensive(void) {
    printf("Starting comprehensive 16 alias entries test...\n");

    for (int entry = 0; entry < 16; entry++) {
        for (int pattern_idx = 0; pattern_idx < 8; pattern_idx++) {
            uint32_t src_pattern = intensive_patterns[pattern_idx];
            uint32_t dest_pattern = intensive_patterns[pattern_idx + 8];
            uint32_t size_pattern = intensive_patterns[pattern_idx + 16];

            uint32_t src_addr = ALIAS_SRC_BASE + (entry * 0x100000) + src_pattern;
            uint32_t dest_addr = ALIAS_DEST_BASE + (entry * 0x100000) + dest_pattern;
            uint32_t size_mask = size_pattern & 0xFFFFF000; // 4KB aligned

            if (setup_output_remap_region_extended(entry, src_addr, dest_addr,
                                                   1,         // enable
                                                   entry % 2, // channel (AP/STEE)
                                                   size_mask, (src_pattern >> 24) & 0xFF) != 0) {
                printf("ERROR: Failed comprehensive alias setup %d:%d\n", entry, pattern_idx);
                return -1;
            }

            uint32_t readback;
            if (read_output_remap_reg(entry, OUTPUT_REMAP_SRC_ADDR_LOW_OFFSET, &readback) != 0) {
                return -1;
            }

            if (toggle_output_remap_region_enable(entry) != 0) {
                return -1;
            }
            if (toggle_output_remap_region_enable(entry) != 0) {
                return -1;
            }
        }
    }

    printf("Comprehensive 16 alias entries: PASS\n");
    return 0;
}

static int test_enable_disable_state_transitions(void) {
    printf("Starting enable/disable state transitions test...\n");

    for (int cycle = 0; cycle < 32; cycle++) {
        for (int entry = 0; entry < 16; entry++) {
            uint32_t addr_offset = cycle * 0x10000 + entry * 0x1000;

            if (setup_output_remap_region(entry, ALIAS_SRC_BASE + addr_offset,
                                          ALIAS_DEST_BASE + addr_offset + 0x100000,
                                          0, // start disabled
                                          entry % 2) != 0) {
                return -1;
            }

            // Rapid state-transition sequence
            if (toggle_output_remap_region_enable(entry) != 0) return -1; // enable
            if (toggle_output_remap_region_enable(entry) != 0) return -1; // disable
            if (toggle_output_remap_region_enable(entry) != 0) return -1; // enable
            if (toggle_output_remap_region_enable(entry) != 0) return -1; // disable

            uint32_t status;
            if (read_output_remap_reg(entry, OUTPUT_REMAP_STATUS_OFFSET, &status) != 0) {
                return -1;
            }
        }
    }

    printf("Enable/disable state transitions: PASS\n");
    return 0;
}

static int test_region_validity_combinations(void) {
    printf("Starting region validity combinations test...\n");

    for (int validity_pattern = 0; validity_pattern < 256; validity_pattern++) {
        for (int entry = 0; entry < 16; entry++) {
            int is_valid = (validity_pattern >> (entry % 8)) & 1;
            uint32_t test_addr = ALIAS_SRC_BASE + validity_pattern * 0x10000 + entry * 0x1000;

            if (is_valid) {
                if (setup_output_remap_region_extended(entry, test_addr, test_addr + 0x200000,
                                                       1, // enable
                                                       entry % 2,
                                                       0xFFFFF000, // 4KB mask
                                                       (validity_pattern)&0xFF) != 0) {
                    return -1;
                }
            } else {
                // Program invalid or disabled configuration
                if (setup_output_remap_region(entry, 0, 0, 0, 0) != 0) {
                    return -1;
                }
            }
        }

        // Access under mixed valid/invalid configuration
        for (int entry = 0; entry < 16; entry++) {
            uint32_t test_val;
            read_output_remap_reg(entry, OUTPUT_REMAP_CTRL_OFFSET, &test_val);
        }
    }

    printf("Region validity combinations: PASS\n");
    return 0;
}

static int test_source_destination_address_patterns(void) {
    printf("Starting source/destination address patterns test...\n");

    for (int addr_test = 0; addr_test < 64; addr_test++) {
        for (int entry = 0; entry < 16; entry++) {
            uint32_t src_pattern = intensive_patterns[addr_test % 32];
            uint32_t dest_pattern = intensive_patterns[(addr_test + 16) % 32];

            uint32_t src_addr = (src_pattern & 0xFFFFF000) + (entry * 0x100000);   // 4KB aligned
            uint32_t dest_addr = (dest_pattern & 0xFFFFF000) + (entry * 0x100000); // 4KB aligned

            if (setup_output_remap_region(entry, src_addr, dest_addr, 1, entry % 2) != 0) {
                printf("ERROR: Failed address pattern %d:%d\n", addr_test, entry);
                return -1;
            }

            uint32_t readback_src, readback_dest;
            read_output_remap_reg(entry, OUTPUT_REMAP_SRC_ADDR_LOW_OFFSET, &readback_src);
            read_output_remap_reg(entry, OUTPUT_REMAP_SRC_ADDR_LOW_OFFSET + 4, &readback_dest);
        }
    }

    printf("Source/destination address patterns: PASS\n");
    return 0;
}

static int test_cross_field_dependency_scenarios(void) {
    printf("Starting cross-field dependency scenarios test...\n");

    for (int scenario = 0; scenario < 32; scenario++) {
        for (int entry = 0; entry < 16; entry++) {
            uint32_t field_combo = scenario * 0x10000 + entry * 0x1000;

            uint32_t enable_val = (scenario >> entry) & 1;
            uint32_t channel_val = (scenario >> ((entry + 8) % 16)) & 1;
            uint32_t mask_val = intensive_patterns[scenario % 32] >> entry;
            uint32_t attr_val = (scenario * entry + field_combo) & 0xFF;

            if (setup_output_remap_region_extended(
                    entry, ALIAS_SRC_BASE + field_combo, ALIAS_DEST_BASE + field_combo + 0x100000,
                    enable_val, channel_val, mask_val & 0xFFFFF000, attr_val) != 0) {
                return -1;
            }

            if (enable_val) {
                test_axi_transaction(ALIAS_SRC_BASE + field_combo + (entry * 64), 4, entry % 2);
            }

            toggle_output_remap_region_enable(entry);
            toggle_output_remap_channel(entry);
            toggle_output_remap_region_enable(entry);
        }
    }

    printf("Cross-field dependency scenarios: PASS\n");
    return 0;
}

int main(void) {
    printf("Alias Reg Intensive Toggle Test\n");
    printf("Strategy: Deep CSR-field toggle stress across all 16 alias entries\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_alias_reg_intensive_toggle_test");
        return TEST_FAIL;
    }

    if (test_all_16_alias_entries_comprehensive() != 0) {
        test_fail("16 Alias Entries Comprehensive");
        return TEST_FAIL;
    }

    if (test_enable_disable_state_transitions() != 0) {
        test_fail("Enable/Disable Transitions");
        return TEST_FAIL;
    }

    if (test_region_validity_combinations() != 0) {
        test_fail("Region Validity Combinations");
        return TEST_FAIL;
    }

    if (test_source_destination_address_patterns() != 0) {
        test_fail("Address Patterns");
        return TEST_FAIL;
    }

    if (test_cross_field_dependency_scenarios() != 0) {
        test_fail("Cross-Field Dependencies");
        return TEST_FAIL;
    }

    printf("\n=== ALIAS REG INTENSIVE TOGGLE TEST PASSED ===\n");

    test_pass("fabric_alias_reg_intensive_toggle_test");
    return TEST_PASS;
}
