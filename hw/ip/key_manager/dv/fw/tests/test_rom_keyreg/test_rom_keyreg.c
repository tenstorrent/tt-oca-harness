/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_keyreg.c
 * @brief T022 - Key handle registry unit test
 *
 * Exercises rom_keyreg.h: init, generate, get_slot, get_crc, destroy,
 * reverse map, invalid-handle rejection, and handle exhaustion.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_keyreg
 */

#include "test_common.h"
#include "rom_keyreg.h"

static rom_km_keyreg_t reg;

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(200000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /* 1. Init: all handles invalid */
    TEST_SUBTEST_START("Init - all handles invalid");
    rom_keyreg_init(&reg);
    {
        uint8_t slot;
        uint32_t i;
        for (i = 1; i <= 255; i++) {
            if (rom_keyreg_get_slot(&reg, (uint8_t)i, &slot) != -1) {
                TEST_FAIL("handle %u should be invalid after init", (unsigned)i);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* 2. Generate sequential handles: expect 1, 2, 3 */
    TEST_SUBTEST_START("Generate sequential handles");
    rom_keyreg_init(&reg);
    {
        int h1 = rom_keyreg_generate(&reg, 0, 1, 0x1111u, (rom_km_dest_bits_t){.raw = 0x04u});
        int h2 = rom_keyreg_generate(&reg, 1, 1, 0x2222u, (rom_km_dest_bits_t){.raw = 0x02u});
        int h3 = rom_keyreg_generate(&reg, 2, 1, 0x3333u, (rom_km_dest_bits_t){.raw = 0x08u});
        TEST_ASSERT_EQ(h1, 1u, "handle 1");
        TEST_ASSERT_EQ(h2, 2u, "handle 2");
        TEST_ASSERT_EQ(h3, 3u, "handle 3");
    }
    TEST_SUBTEST_PASS();

    /* 3. get_slot / get_crc / get_dest_valid */
    TEST_SUBTEST_START("get_slot, get_crc, and get_dest_valid");
    {
        uint8_t slot;
        uint32_t crc;
        rom_km_dest_bits_t dest_valid;
        int rc;

        rc = rom_keyreg_get_slot(&reg, 1, &slot);
        TEST_ASSERT_EQ(rc, 0u, "get_slot(1) rc");
        TEST_ASSERT_EQ(slot, 0u, "get_slot(1) value");

        rc = rom_keyreg_get_slot(&reg, 2, &slot);
        TEST_ASSERT_EQ(rc, 0u, "get_slot(2) rc");
        TEST_ASSERT_EQ(slot, 1u, "get_slot(2) value");

        rc = rom_keyreg_get_crc(&reg, 1, &crc);
        TEST_ASSERT_EQ(rc, 0u, "get_crc(1) rc");
        TEST_ASSERT_EQ(crc, 0x1111u, "get_crc(1) value");

        rc = rom_keyreg_get_crc(&reg, 3, &crc);
        TEST_ASSERT_EQ(rc, 0u, "get_crc(3) rc");
        TEST_ASSERT_EQ(crc, 0x3333u, "get_crc(3) value");

        rc = rom_keyreg_get_dest_valid(&reg, 2, &dest_valid);
        TEST_ASSERT_EQ(rc, 0u, "get_dest_valid(2) rc");
        TEST_ASSERT_EQ(dest_valid.raw, 0x02u, "get_dest_valid(2) value");
    }
    TEST_SUBTEST_PASS();

    /* 4. Invalid handle: handle 0 and destroyed handle */
    TEST_SUBTEST_START("Invalid handle rejection");
    {
        uint8_t slot;
        int rc;

        rc = rom_keyreg_get_slot(&reg, 0, &slot);
        if (rc != -1) {
            TEST_FAIL("get_slot(0) should return -1, got %d", rc);
        }

        rom_keyreg_destroy(&reg, 2);
        rc = rom_keyreg_get_slot(&reg, 2, &slot);
        if (rc != -1) {
            TEST_FAIL("get_slot(destroyed=2) should return -1, got %d", rc);
        }
    }
    TEST_SUBTEST_PASS();

    /* 5. Destroy: generate, destroy, verify error */
    TEST_SUBTEST_START("Destroy");
    rom_keyreg_init(&reg);
    {
        int h = rom_keyreg_generate(&reg, 10, 1, 0xAAAAu, (rom_km_dest_bits_t){.raw = 0x01u});
        TEST_ASSERT_EQ(h, 1u, "generated handle");

        int rc = rom_keyreg_destroy(&reg, (uint8_t)h);
        TEST_ASSERT_EQ(rc, 0u, "destroy rc");

        uint8_t slot;
        rc = rom_keyreg_get_slot(&reg, (uint8_t)h, &slot);
        if (rc != -1) {
            TEST_FAIL("get_slot after destroy should return -1, got %d", rc);
        }

        rom_km_dest_bits_t dest_valid;
        rc = rom_keyreg_get_dest_valid(&reg, (uint8_t)h, &dest_valid);
        if (rc != -1) {
            TEST_FAIL("get_dest_valid after destroy should return -1, got %d", rc);
        }
    }
    TEST_SUBTEST_PASS();

    /* 6. Reverse map: slot_to_handle */
    TEST_SUBTEST_START("Reverse map (slot_to_handle)");
    rom_keyreg_init(&reg);
    {
        int h = rom_keyreg_generate(&reg, 5, 2, 0xBBBBu, (rom_km_dest_bits_t){.raw = 0x0Cu});
        if (h < 1) {
            TEST_FAIL("generate returned %d", h);
        }
        uint8_t h5 = rom_keyreg_get_handle(&reg, 5);
        uint8_t h6 = rom_keyreg_get_handle(&reg, 6);
        TEST_ASSERT_EQ(h5, (uint32_t)h, "slot_to_handle[5]");
        TEST_ASSERT_EQ(h6, (uint32_t)h, "slot_to_handle[6]");

        uint8_t h4 = rom_keyreg_get_handle(&reg, 4);
        TEST_ASSERT_EQ(h4, 0u, "slot_to_handle[4] should be null");
    }
    TEST_SUBTEST_PASS();

    /* 7. Exhaustion: allocate handles 1..255, 256th must fail */
    TEST_SUBTEST_START("Handle exhaustion");
    rom_keyreg_init(&reg);
    {
        uint32_t i;
        for (i = 0; i < 255; i++) {
            int h = rom_keyreg_generate(&reg, (uint8_t)(i % ROM_KM_KPV_NUM_SLOTS), 1, i,
                                        (rom_km_dest_bits_t){.raw = 0x04u});
            if (h < 1) {
                TEST_FAIL("generate failed at i=%u, returned %d", (unsigned)i, h);
            }
        }
        int overflow = rom_keyreg_generate(&reg, 0, 1, 0xFFFFu, (rom_km_dest_bits_t){.raw = 0x04u});
        if (overflow != -1) {
            TEST_FAIL("256th generate should return -1, got %d", overflow);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
