/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_memset.c
 * @brief Optimized rom_memset for ROM firmware (RV32EMC bare-metal)
 *
 * ROM-namespaced fill routine. Uses a word-aligned fast path (sw) when the
 * destination is 4-byte aligned, falling back to byte stores for unaligned
 * heads/tails. The register keyword encourages the compiler to keep loop-hot
 * variables in the 16-register RV32E file rather than spilling to SRAM.
 */

#include <stdint.h>
#include <stddef.h>

void *rom_memset(void *dest, int c, size_t n);

/**
 * @brief Fill n bytes of dest with byte value c (ROM API).
 *
 * Uses a word-aligned fast path when the destination is 4-byte aligned.
 *
 * @param[out] dest Destination buffer.
 * @param[in]  c    Fill byte (low 8 bits used).
 * @param[in]  n    Number of bytes to fill.
 * @return dest.
 */
void *rom_memset(void *dest, int c, size_t n) {
    register uint8_t *d = (uint8_t *)dest;
    register size_t remaining = n;
    register uint8_t byte = (uint8_t)c;

    if (remaining >= 4 && ((uintptr_t)d & 3) == 0) {
        register uint32_t word = (uint32_t)byte;
        word |= word << 8;
        word |= word << 16;
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
        register uint32_t *dw = (uint32_t *)d;
#pragma GCC diagnostic pop
        while (remaining >= 4) {
            *dw++ = word;
            remaining -= 4;
        }
        d = (uint8_t *)dw;
    }

    while (remaining-- != 0) {
        *d++ = byte;
    }

    return dest;
}

/**
 * @brief Alias for rom_memset for code that uses the standard memset symbol.
 *
 * Used by test builds and any code that calls memset(); resolves to the
 * same implementation as rom_memset.
 *
 * @param[out] dest Destination buffer.
 * @param[in]  c    Fill byte (low 8 bits used).
 * @param[in]  n    Number of bytes to fill.
 * @return dest.
 */
void *memset(void *dest, int c, size_t n) __attribute__((alias("rom_memset")));
