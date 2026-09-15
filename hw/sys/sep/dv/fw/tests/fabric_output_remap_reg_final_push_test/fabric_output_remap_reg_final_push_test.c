/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * fabric_output_remap_reg_final_push_test
 *
 * Strategy: CSR field toggle coverage
 *
 * Focus on precise CSR-field toggle coverage in output_remap_reg
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// CSR toggle scenario count
#define CSR_TOGGLE_SCENARIOS 32

// CSR field-pattern definitions
#define ADDR_PATTERN_A 0xAAAAAAAA
#define ADDR_PATTERN_B 0x55555555
#define ADDR_PATTERN_C 0xCCCCCCCC
#define ADDR_PATTERN_D 0x33333333

#define ENABLE_PATTERN_FULL 0xFFFFFFFF
#define ENABLE_PATTERN_ALT 0x55555555
#define ENABLE_PATTERN_INV 0xAAAAAAAA

#define CHANNEL_PATTERN_AP 0x00000000
#define CHANNEL_PATTERN_STEE 0xFFFFFFFF

static int test_address_field_precise_toggle(void) {
    printf("Starting address field precise toggle tests...\n");

    // Scenario 1: Precise address-field toggle
    uint32_t addr_patterns[] = {
        0x00000001, 0x00000002, 0x00000004, 0x00000008, // single-bit patterns
        0x00000010, 0x00000020, 0x00000040, 0x00000080, 0x00000100, 0x00000200,
        0x00000400, 0x00000800, 0x00001000, 0x00002000, 0x00004000, 0x00008000,
        0x00010000, 0x00020000, 0x00040000, 0x00080000, 0x00100000, 0x00200000,
        0x00400000, 0x00800000, 0x01000000, 0x02000000, 0x04000000, 0x08000000,
        0x10000000, 0x20000000, 0x40000000, 0x80000000 // full 32-bit coverage
    };

    for (int i = 0; i < 32; i++) {
        int region = i % 16; // use all 16 regions
        uint32_t src_addr = 0x40000000 + addr_patterns[i];
        uint32_t dest_addr = 0x50000000 + (addr_patterns[i] >> 1);

        if (setup_output_remap_region(region, src_addr, dest_addr, 1,
                                      (i % 2) ? AP_CHANNEL : STEE_CHANNEL) != 0) {
            printf("ERROR: Failed to setup address pattern %d\n", i);
            return -1;
        }

        uint32_t readback;
        if (read_output_remap_reg(region, OUTPUT_REMAP_SRC_ADDR_LOW_OFFSET, &readback) != 0) {
            printf("ERROR: Failed to read address pattern %d\n", i);
            return -1;
        }
    }

    printf("Address field precise toggle: PASS\n");
    return 0;
}

static int test_enable_bit_combinations(void) {
    printf("Starting enable bit combination tests...\n");

    // Scenario 2: Deep enable-bit toggle combinations
    uint32_t enable_patterns[] = {
        0x00000001, 0x00000003, 0x00000007, 0x0000000F, // cumulative patterns
        0x0000001F, 0x0000003F, 0x0000007F, 0x000000FF, 0x000001FF, 0x000003FF, 0x000007FF,
        0x00000FFF, 0x00001FFF, 0x00003FFF, 0x00007FFF, 0x0000FFFF, 0x0001FFFF, 0x0003FFFF,
        0x0007FFFF, 0x000FFFFF, 0x001FFFFF, 0x003FFFFF, 0x007FFFFF, 0x00FFFFFF, 0x01FFFFFF,
        0x03FFFFFF, 0x07FFFFFF, 0x0FFFFFFF, 0x1FFFFFFF, 0x3FFFFFFF, 0x7FFFFFFF, 0xFFFFFFFF};

    for (int i = 0; i < 32; i++) {
        int region = i % 16;

        // Set enable mode
        if (setup_output_remap_region_extended(region, 0x60000000 + i * 0x1000,
                                               0x70000000 + i * 0x1000,
                                               enable_patterns[i] & 1,           // enable bit
                                               (enable_patterns[i] >> 1) & 1,    // channel bit
                                               enable_patterns[i] >> 2,          // mask
                                               enable_patterns[i] >> 16) != 0) { // attr
            printf("ERROR: Failed enable combination %d\n", i);
            return -1;
        }

        if (toggle_output_remap_region_enable(region) != 0) {
            printf("ERROR: Failed enable toggle %d\n", i);
            return -1;
        }

        if (toggle_output_remap_region_enable(region) != 0) {
            printf("ERROR: Failed enable re-toggle %d\n", i);
            return -1;
        }
    }

    printf("Enable bit combinations: PASS\n");
    return 0;
}

static int test_channel_selection_deep_toggle(void) {
    printf("Starting channel selection deep toggle tests...\n");

    // Scenario 3: Deep channel-selection toggle
    for (int cycle = 0; cycle < 16; cycle++) {
        for (int region = 0; region < 16; region++) {
            uint32_t base_addr = 0x80000000 + cycle * 0x10000 + region * 0x1000;

            // AP channel setup
            if (setup_output_remap_region(region, base_addr, base_addr + 0x100000, 1, AP_CHANNEL) !=
                0) {
                return -1;
            }

            // Toggle to STEE channel
            if (toggle_output_remap_channel(region) != 0) {
                printf("ERROR: Failed channel toggle %d:%d\n", cycle, region);
                return -1;
            }

            // Toggle back to AP channel
            if (toggle_output_remap_channel(region) != 0) {
                printf("ERROR: Failed channel re-toggle %d:%d\n", cycle, region);
                return -1;
            }
        }
    }

    printf("Channel selection deep toggle: PASS\n");
    return 0;
}

static int test_size_mask_full_toggle(void) {
    printf("Starting size mask full toggle tests...\n");

    // Scenario 4: Full size-mask toggle coverage
    uint32_t size_masks[] = {0x00000FFF, 0x00001FFF, 0x00003FFF, 0x00007FFF, 0x0000FFFF, 0x0001FFFF,
                             0x0003FFFF, 0x0007FFFF, 0x000FFFFF, 0x001FFFFF, 0x003FFFFF, 0x007FFFFF,
                             0x00FFFFFF, 0x01FFFFFF, 0x03FFFFFF, 0x07FFFFFF, 0x0FFFFFFF, 0x1FFFFFFF,
                             0x3FFFFFFF, 0x7FFFFFFF, 0xFFFFFFFF, 0x55555555, 0xAAAAAAAA, 0xCCCCCCCC,
                             0x33333333, 0x0F0F0F0F, 0xF0F0F0F0, 0x00FF00FF, 0xFF00FF00, 0x0000FFFF,
                             0xFFFF0000, 0x12345678};

    for (int i = 0; i < 32; i++) {
        int region = i % 16;

        if (setup_output_remap_region_extended(region, 0x90000000 + i * 0x10000,
                                               0xA0000000 + i * 0x10000,
                                               1,     // enable
                                               i % 2, // channel
                                               size_masks[i], (size_masks[i] >> 16) & 0xFF) != 0) {
            printf("ERROR: Failed size mask setup %d\n", i);
            return -1;
        }

        uint32_t readback_mask;
        if (read_output_remap_reg(region, OUTPUT_REMAP_CTRL_OFFSET, &readback_mask) != 0) {
            printf("ERROR: Failed size mask readback %d\n", i);
            return -1;
        }
    }

    printf("Size mask full toggle: PASS\n");
    return 0;
}

static int test_attribute_flag_complete_toggle(void) {
    printf("Starting attribute flag complete toggle tests...\n");

    // Scenario 5: Full attribute-flag toggle
    for (int attr_cycle = 0; attr_cycle < 256; attr_cycle++) { // full 8-bit attribute coverage
        int region = attr_cycle % 16;
        uint32_t test_attr = attr_cycle;

        if (setup_output_remap_region_extended(region, 0xB0000000 + attr_cycle * 0x1000,
                                               0xC0000000 + attr_cycle * 0x1000,
                                               1,                       // enable
                                               attr_cycle % 2,          // channel
                                               0xFFFF0000 | attr_cycle, // mask with attr
                                               test_attr) != 0) {
            printf("ERROR: Failed attribute setup %d\n", attr_cycle);
            return -1;
        }

        uint32_t status_readback;
        if (read_output_remap_reg(region, OUTPUT_REMAP_STATUS_OFFSET, &status_readback) != 0) {
            printf("ERROR: Failed attribute status readback %d\n", attr_cycle);
            return -1;
        }
    }

    printf("Attribute flag complete toggle: PASS\n");
    return 0;
}

int main(void) {
    printf("Output Remap Reg Final Push Test\n");
    printf("Strategy: Full scan of remaining CSR toggle bits\n\n");

    if (init_sep_fabric() != 0) {
        test_fail("fabric_output_remap_reg_final_push_test");
        return TEST_FAIL;
    }

    // Run all CSR-toggle scenarios
    if (test_address_field_precise_toggle() != 0) {
        test_fail("Address Field Toggle");
        return TEST_FAIL;
    }

    if (test_enable_bit_combinations() != 0) {
        test_fail("Enable Bit Combinations");
        return TEST_FAIL;
    }

    if (test_channel_selection_deep_toggle() != 0) {
        test_fail("Channel Selection Toggle");
        return TEST_FAIL;
    }

    if (test_size_mask_full_toggle() != 0) {
        test_fail("Size Mask Toggle");
        return TEST_FAIL;
    }

    if (test_attribute_flag_complete_toggle() != 0) {
        test_fail("Attribute Flag Toggle");
        return TEST_FAIL;
    }

    printf("\n=== OUTPUT REMAP REG FINAL PUSH TEST PASSED ===\n");

    test_pass("fabric_output_remap_reg_final_push_test");
    return TEST_PASS;
}
