/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_crc.c
 * @brief CRC-8/ROHC and CRC-32C Castagnoli implementations backed by PicoRV32 PCPI helpers.
 */

#include "rom_crc.h"
#include "rom_picorv32.h"

/**
 * @brief Compute CRC-8/ROHC over a byte buffer.
 *
 * @param[in] data Input bytes.
 * @param[in] len  Number of bytes.
 * @return CRC-8 value (init 0xFF, poly reflected 0xE0, XorOut 0x00).
 */
uint8_t rom_crc8_rohc(const uint8_t *data, uint32_t len) {
    uint32_t crc = 0xFFu;

    for (uint32_t i = 0; i < len; i++) {
        crc = rom_picorv32_crc8_rohc_update(crc, data[i]);
    }

    return (uint8_t)crc;
}

/**
 * @brief Compute CRC-32C (Castagnoli) over a byte buffer.
 *
 * @param[in] data Input bytes.
 * @param[in] len  Number of bytes.
 * @return CRC-32C value (init 0xFFFFFFFF, XorOut 0xFFFFFFFF).
 */
uint32_t rom_crc32c(const uint8_t *data, uint32_t len) {
    uint32_t crc = 0xFFFFFFFFu;

    while (len != 0u && (((uintptr_t)data) & 0x3u) != 0u) {
        crc = rom_picorv32_crc32c_byte_update(crc, *data);
        data++;
        len--;
    }

    while (len >= 4u) {
        const uint32_t *aligned_word = (const uint32_t *)__builtin_assume_aligned(data, 4);
        uint32_t word = *aligned_word;
        crc = rom_picorv32_crc32c_word_update(crc, word);
        data += 4;
        len -= 4u;
    }

    while (len != 0u) {
        crc = rom_picorv32_crc32c_byte_update(crc, *data);
        data++;
        len--;
    }

    return crc ^ 0xFFFFFFFFu;
}
