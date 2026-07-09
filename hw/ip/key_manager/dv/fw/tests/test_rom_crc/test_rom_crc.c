/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_crc.c
 * @brief CRC PCPI functional, chaining, and trap tests.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_crc
 */

#include "test_common.h"
#include "rom_boot.h"
#include "rom_crc.h"
#include "rom_defs.h"
#include "rom_picorv32.h"

#define TEST_CRC32C_WORD_RAW_INSN 0x58B5050Bu
#define TEST_CRC32C_BYTE_RAW_INSN 0x58B5150Bu
#define TEST_CRC8_ROHC_RAW_INSN 0x58B5250Bu
#define TEST_CRC_BAD_RAW_INSN 0x58B5350Bu

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

static inline uint32_t raw_crc32c_word_update(uint32_t state, uint32_t word) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = word;

    __asm__ volatile(".word 0x58B5050B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

static inline uint32_t raw_crc32c_byte_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5150B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

static inline uint32_t raw_crc8_rohc_update(uint32_t state, uint32_t data) {
    register uint32_t a0 __asm__("a0") = state;
    register uint32_t a1 __asm__("a1") = data;

    __asm__ volatile(".word 0x58B5250B" : "+r"(a0) : "r"(a1) :);
    return a0;
}

static uint32_t pack_le32(const uint8_t *data) {
    return ((uint32_t)data[0]) | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16) |
           ((uint32_t)data[3] << 24);
}

static uint32_t crc32c_ref_step(uint32_t state, uint8_t data_byte) {
    uint32_t crc = state ^ data_byte;

    for (uint32_t bit_idx = 0; bit_idx < 8u; bit_idx++) {
        if (crc & 1u) {
            crc = (crc >> 1) ^ 0x82F63B78u;
        } else {
            crc >>= 1;
        }
    }

    return crc;
}

static uint32_t crc32c_ref_word_update(uint32_t state, uint32_t word) {
    state = crc32c_ref_step(state, (uint8_t)(word >> 0));
    state = crc32c_ref_step(state, (uint8_t)(word >> 8));
    state = crc32c_ref_step(state, (uint8_t)(word >> 16));
    state = crc32c_ref_step(state, (uint8_t)(word >> 24));
    return state;
}

static uint32_t crc32c_ref_public(const uint8_t *data, uint32_t len) {
    uint32_t state = 0xFFFFFFFFu;

    while (len >= 4u) {
        state = crc32c_ref_word_update(state, pack_le32(data));
        data += 4;
        len -= 4u;
    }

    while (len != 0u) {
        state = crc32c_ref_step(state, *data);
        data++;
        len--;
    }

    return state ^ 0xFFFFFFFFu;
}

static uint32_t crc8_rohc_ref_step(uint32_t state, uint8_t data_byte) {
    uint32_t crc = (state ^ data_byte) & 0xFFu;

    for (uint32_t bit_idx = 0; bit_idx < 8u; bit_idx++) {
        if (crc & 1u) {
            crc = (crc >> 1) ^ 0xE0u;
        } else {
            crc >>= 1;
        }
        crc &= 0xFFu;
    }

    return crc & 0xFFu;
}

static uint8_t crc8_rohc_ref_public(const uint8_t *data, uint32_t len) {
    uint32_t state = 0xFFu;

    for (uint32_t i = 0; i < len; i++) {
        state = crc8_rohc_ref_step(state, data[i]);
    }

    return (uint8_t)state;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000u)) {
        TEST_FAIL("Failed to set test timeout");
    }

    if (tb_check_unrecoverable_restart(1000u)) {
        uint32_t fault_code;

        if (!tb_get_unrecoverable_fault_code(1000u, &fault_code)) {
            TEST_FAIL("Failed to get unrecoverable fault code");
        }

        TEST_ASSERT_EQ(fault_code, (uint32_t)(int32_t)ROM_KM_UFAULT_ILLEGAL_INSN,
                       "unsupported CRC encoding fault code");
    } else {
        if (!tb_drbg_set_seed(0x2130u, 5000u)) {
            TEST_FAIL("tb_drbg_set_seed failed");
        }

        if (!tb_set_unrecoverable_watch(1, 1000u)) {
            TEST_FAIL("Failed to arm unrecoverable watcher");
        }

        rom_boot_init();
        __asm__ volatile(".word 0x58B5350B");
        TEST_FAIL("Unsupported CRC encoding did not trap");
        return 0;
    }

    TEST_SUBTEST_START("Raw CRC custom instruction smoke");
    {
        uint32_t word_state = raw_crc32c_word_update(0xFFFFFFFFu, 0x33221100u);
        uint32_t byte_state = raw_crc32c_byte_update(0xFFFFFFFFu, 0xA5A50042u);
        uint32_t crc8_state = raw_crc8_rohc_update(0xFFu, 0x12345678u);

        TEST_ASSERT_EQ(word_state, crc32c_ref_word_update(0xFFFFFFFFu, 0x33221100u),
                       "raw CRC-32C word state");
        TEST_ASSERT_EQ(byte_state, crc32c_ref_step(0xFFFFFFFFu, 0x42u), "raw CRC-32C byte state");
        TEST_ASSERT_EQ(crc8_state, crc8_rohc_ref_step(0xFFu, 0x78u), "raw CRC-8 state");
        TEST_ASSERT_EQ(crc8_state >> 8, 0u, "raw CRC-8 zero extension");
        TEST_ASSERT_EQ(raw_crc32c_word_update(0xFFFFFFFFu, 0x33221100u), word_state,
                       "raw CRC-32C word deterministic");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-8 public golden vectors");
    {
        const uint8_t byte0 = 0x00;
        const uint8_t byteff = 0xFF;
        const uint8_t data123456789[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
        const uint8_t a[] = {'a'};
        const uint8_t ab[] = {'a', 'b'};
        const uint8_t abc[] = {'a', 'b', 'c'};
        const uint8_t zeros[4] = {0};
        const uint8_t ff[4] = {0xFF, 0xFF, 0xFF, 0xFF};

        TEST_ASSERT_EQ(rom_crc8_rohc((const uint8_t *)0, 0), 0xFFu, "CRC-8 empty");
        TEST_ASSERT_EQ(rom_crc8_rohc(&byte0, 1), 0xCFu, "CRC-8 single 0x00");
        TEST_ASSERT_EQ(rom_crc8_rohc(&byteff, 1), 0x00u, "CRC-8 single 0xFF");
        TEST_ASSERT_EQ(rom_crc8_rohc(data123456789, 9), 0xD0u, "CRC-8 123456789");
        TEST_ASSERT_EQ(rom_crc8_rohc(a, 1), 0x16u, "CRC-8 a");
        TEST_ASSERT_EQ(rom_crc8_rohc(ab, 2), 0x53u, "CRC-8 ab");
        TEST_ASSERT_EQ(rom_crc8_rohc(abc, 3), 0x24u, "CRC-8 abc");
        TEST_ASSERT_EQ(rom_crc8_rohc(zeros, 4), 0x8Bu, "CRC-8 4 zero bytes");
        TEST_ASSERT_EQ(rom_crc8_rohc(ff, 4), 0xF0u, "CRC-8 4 0xFF bytes");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-8 header chaining and low-byte handling");
    {
        const rom_km_msg_header_t headers[] = {
            {.seq_num = 0x01, .id = ROM_KM_CMD_HW_VER, .payload_len = 0x00, .header_crc8 = 0x00},
            {.seq_num = 0x02,
             .id = ROM_KM_CMD_KEY_TRANSFER,
             .payload_len = 0x02,
             .header_crc8 = 0x00},
            {.seq_num = 0x81, .id = ROM_KM_RESP_CMD, .payload_len = 0x01, .header_crc8 = 0x00},
            {.seq_num = 0x82,
             .id = ROM_KM_RESP_KM_READY,
             .payload_len = 0x00,
             .header_crc8 = 0x00}};

        for (uint32_t i = 0; i < (sizeof(headers) / sizeof(headers[0])); i++) {
            uint32_t raw_state = 0xFFu;
            const uint8_t *bytes = (const uint8_t *)&headers[i];
            uint8_t expected_crc = crc8_rohc_ref_public(bytes, 3u);

            raw_state = raw_crc8_rohc_update(raw_state, 0xFF000000u | bytes[0]);
            raw_state = raw_crc8_rohc_update(raw_state, 0xABCD0000u | bytes[1]);
            raw_state = raw_crc8_rohc_update(raw_state, 0x12340000u | bytes[2]);

            TEST_ASSERT_EQ((uint8_t)raw_state, expected_crc, "raw header CRC-8");
            TEST_ASSERT_EQ(raw_state >> 8, 0u, "header CRC-8 zero extended");
            TEST_ASSERT_EQ(rom_crc8_rohc(bytes, 3u), expected_crc, "public header CRC-8");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-32C public golden vectors");
    {
        const uint8_t data123456789[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
        const uint8_t a[] = {'a'};
        const uint8_t ab[] = {'a', 'b'};
        const uint8_t abc[] = {'a', 'b', 'c'};
        const uint8_t abcd[] = {'a', 'b', 'c', 'd'};
        const uint8_t abcde[] = {'a', 'b', 'c', 'd', 'e'};
        const uint8_t abcdef[] = {'a', 'b', 'c', 'd', 'e', 'f'};
        const uint8_t abcdefg[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g'};
        const uint8_t abcdefgh[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'};
        const uint8_t abcdefghi[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'};
        const uint8_t msg[] = "The quick brown fox jumps over the lazy dog";

        TEST_ASSERT_EQ(rom_crc32c((const uint8_t *)0, 0), 0x00000000u, "CRC-32C empty");
        TEST_ASSERT_EQ(rom_crc32c(data123456789, 9), 0xE3069283u, "CRC-32C 123456789");
        TEST_ASSERT_EQ(rom_crc32c(a, 1), 0xC1D04330u, "CRC-32C a");
        TEST_ASSERT_EQ(rom_crc32c(ab, 2), 0xE2A22936u, "CRC-32C ab");
        TEST_ASSERT_EQ(rom_crc32c(abc, 3), 0x364B3FB7u, "CRC-32C abc");
        TEST_ASSERT_EQ(rom_crc32c(abcd, 4), 0x92C80A31u, "CRC-32C abcd");
        TEST_ASSERT_EQ(rom_crc32c(abcde, 5), 0xC450D697u, "CRC-32C abcde");
        TEST_ASSERT_EQ(rom_crc32c(abcdef, 6), 0x53BCEFF1u, "CRC-32C abcdef");
        TEST_ASSERT_EQ(rom_crc32c(abcdefg, 7), 0xE627F441u, "CRC-32C abcdefg");
        TEST_ASSERT_EQ(rom_crc32c(abcdefgh, 8), 0x0A9421B7u, "CRC-32C abcdefgh");
        TEST_ASSERT_EQ(rom_crc32c(abcdefghi, 9), 0x2DDC99FCu, "CRC-32C abcdefghi");
        TEST_ASSERT_EQ(rom_crc32c(msg, sizeof(msg) - 1u), 0x22620404u, "CRC-32C quick brown fox");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-32C lengths, word packing, and chaining");
    {
        static const uint8_t payload[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE};
        static const uint32_t lengths[] = {0u, 1u, 2u, 3u, 4u, 5u, 7u, 8u};

        TEST_ASSERT_EQ(raw_crc32c_word_update(0xFFFFFFFFu, pack_le32(payload)),
                       crc32c_ref_word_update(0xFFFFFFFFu, pack_le32(payload)),
                       "CRC-32C little-endian word packing");

        for (uint32_t i = 0; i < (sizeof(lengths) / sizeof(lengths[0])); i++) {
            uint32_t len = lengths[i];
            uint32_t byte_state = 0xFFFFFFFFu;
            uint32_t mixed_state = 0xFFFFFFFFu;
            uint32_t expected_crc = crc32c_ref_public(payload, len);
            uint32_t pos = 0u;

            while (pos < len) {
                byte_state = raw_crc32c_byte_update(byte_state, 0xAA000000u | payload[pos]);
                pos++;
            }

            pos = 0u;
            while ((len - pos) >= 4u) {
                mixed_state = raw_crc32c_word_update(mixed_state, pack_le32(&payload[pos]));
                pos += 4u;
            }
            while (pos < len) {
                mixed_state = raw_crc32c_byte_update(mixed_state, 0x55000000u | payload[pos]);
                pos++;
            }

            TEST_ASSERT_EQ(rom_crc32c(payload, len), expected_crc, "public CRC-32C length");
            TEST_ASSERT_EQ(byte_state ^ 0xFFFFFFFFu, expected_crc, "byte-only CRC-32C");
            TEST_ASSERT_EQ(mixed_state ^ 0xFFFFFFFFu, expected_crc, "mixed CRC-32C");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-32C unaligned entry covers align, word, and tail");
    {
        static const uint32_t aligned_words[] = {0x03020100u, 0x07060504u, 0x0B0A0908u};
        const uint8_t *aligned = (const uint8_t *)aligned_words;

        TEST_ASSERT_EQ(((uintptr_t)aligned) & 0x3u, 0u, "aligned CRC-32C test buffer");
        TEST_ASSERT_EQ(rom_crc32c(aligned + 1u, 8u), crc32c_ref_public(aligned + 1u, 8u),
                       "CRC-32C offset 1 covers align-word-tail");
        TEST_ASSERT_EQ(rom_crc32c(aligned + 2u, 7u), crc32c_ref_public(aligned + 2u, 7u),
                       "CRC-32C offset 2 covers align-word-tail");
        TEST_ASSERT_EQ(rom_crc32c(aligned + 3u, 6u), crc32c_ref_public(aligned + 3u, 6u),
                       "CRC-32C offset 3 covers align-word-tail");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CRC-32C resume from intermediate state");
    {
        static const uint8_t data[7] = {0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC};
        uint32_t state = raw_crc32c_word_update(0xFFFFFFFFu, pack_le32(data));
        uint32_t resumed_state = raw_crc32c_byte_update(state, 0xFF000000u | data[4]);
        resumed_state = raw_crc32c_byte_update(resumed_state, 0xAB000000u | data[5]);
        resumed_state = raw_crc32c_byte_update(resumed_state, 0xCD000000u | data[6]);

        TEST_ASSERT_EQ(resumed_state ^ 0xFFFFFFFFu, crc32c_ref_public(data, sizeof(data)),
                       "resumed CRC-32C final value");
        TEST_ASSERT_EQ(rom_picorv32_crc32c_word_update(0xFFFFFFFFu, pack_le32(data)), state,
                       "wrapper CRC-32C word state");
        TEST_ASSERT_EQ(rom_picorv32_crc32c_byte_update(state, data[4]),
                       raw_crc32c_byte_update(state, data[4]), "wrapper CRC-32C byte state");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
