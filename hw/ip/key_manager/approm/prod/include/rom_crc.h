/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_crc.h
 * @brief CRC-8/ROHC and CRC-32C Castagnoli firmware CRC APIs.
 */

#ifndef ROM_CRC_H
#define ROM_CRC_H

#include <stdint.h>

/**
 * @brief Compute CRC-8/ROHC over a byte buffer.
 *
 * Reflected poly 0xE0, init 0xFF, RefIn/RefOut, XorOut 0x00.
 * Check value ("123456789"): 0xD0.
 *
 * @param data Pointer to input bytes.
 * @param len Number of bytes.
 * @return CRC-8/ROHC value.
 */
uint8_t rom_crc8_rohc(const uint8_t *data, uint32_t len);

/**
 * @brief Compute CRC-32C (Castagnoli) over a byte buffer.
 *
 * Reflected poly 0x82F63B78, init 0xFFFFFFFF, RefIn/RefOut,
 * XorOut 0xFFFFFFFF.
 * Check value ("123456789"): 0xE3069283.
 *
 * @param data Pointer to input bytes.
 * @param len Number of bytes.
 * @return CRC-32C value.
 */
uint32_t rom_crc32c(const uint8_t *data, uint32_t len);

#endif /* ROM_CRC_H */
