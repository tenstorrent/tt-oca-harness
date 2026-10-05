/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_memcpy.c
 * @brief Optimized rom_memcpy for ROM firmware (RV32EMC bare-metal)
 *
 * ROM-namespaced copy routine. Uses a word-aligned fast path (lw/sw) when
 * both pointers are 4-byte aligned, falling back to byte copies for
 * unaligned heads/tails. The register keyword encourages the compiler to
 * keep loop-hot variables in the 16-register RV32E file rather than
 * spilling to SRAM.
 */

#include <stdint.h>
#include <stddef.h>

void *rom_memcpy(void *dest, const void *src, size_t n);

/**
 * @brief Copy n bytes from src to dest (ROM API).
 *
 * Uses word-aligned fast path when both pointers are 4-byte aligned.
 *
 * @param[out] dest Destination buffer.
 * @param[in]  src  Source buffer.
 * @param[in]  n    Number of bytes to copy.
 * @return dest.
 */
void *rom_memcpy(void *dest, const void *src, size_t n) {
    register uint8_t *d = (uint8_t *)dest;
    register const uint8_t *s = (const uint8_t *)src;
    register size_t remaining = n;

    if (remaining >= 4 && ((uintptr_t)d & 3) == 0 && ((uintptr_t)s & 3) == 0) {
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-align"
        register uint32_t *dw = (uint32_t *)d;
        register const uint32_t *sw = (const uint32_t *)s;
#pragma GCC diagnostic pop
        while (remaining >= 4) {
            *dw++ = *sw++;
            remaining -= 4;
        }
        d = (uint8_t *)dw;
        s = (const uint8_t *)sw;
    }

    while (remaining-- != 0) {
        *d++ = *s++;
    }

    return dest;
}

/**
 * @brief Alias for rom_memcpy for code that uses the standard memcpy symbol.
 *
 * Used by test builds and any code that calls memcpy(); resolves to the
 * same implementation as rom_memcpy.
 *
 * @param[out] dest Destination buffer.
 * @param[in]  src  Source buffer.
 * @param[in]  n    Number of bytes to copy.
 * @return dest.
 */
void *memcpy(void *dest, const void *src, size_t n) __attribute__((alias("rom_memcpy")));
