/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file rom_secutil.c
 * @brief Side-channel- and fault-hardened memory helpers.
 */

#include <stdint.h>
#include <stddef.h>

#include "rom_secutil.h"

int rom_const_time_memcmp(const void *ptr1, const void *ptr2, size_t num) {
    const uint8_t *a = (const uint8_t *)ptr1;
    const uint8_t *b = (const uint8_t *)ptr2;

    /*
     * Use volatile to prevent the compiler from optimizing away the execution
     * counter or reordering operations.
     */
    volatile uint8_t result = 0;
    volatile size_t executed = 0;

    for (size_t i = 0; i < num; i++) {
        result = (uint8_t)(result | (uint8_t)(a[i] ^ b[i]));
        executed++;
    }

    /*
     * Constant-time combination of comparison result and glitch detection:
     *  - result        : 0 if all bytes matched, non-zero if any differed
     *  - executed ^ num: 0 if the loop ran the expected count, non-zero if glitched
     * OR them so fail is 0 only when both checks pass.
     */
    size_t fail = (size_t)result | (executed ^ num);

    /*
     * Branch-free normalization to 0/1: for any non-zero value, either the
     * value or its two's-complement negation has the MSB set; for zero, both
     * are zero. The MSB (shifted to bit 0) is therefore 1 iff fail != 0.
     */
    return (int)((fail | ((size_t)0 - fail)) >> (sizeof(size_t) * 8u - 1u));
}

int rom_pointers_are_equal_ct(const void *ptr1, const void *ptr2) {
    volatile size_t p1 = (size_t)ptr1;
    volatile size_t p2 = (size_t)ptr2;
    volatile size_t diff = p1 ^ p2;

    /* Same MSB-extraction trick as rom_const_time_memcmp, inverted: 1 if equal. */
    return (int)((size_t)1 ^ ((diff | ((size_t)0 - diff)) >> (sizeof(size_t) * 8u - 1u)));
}

void rom_secure_memzero(void *ptr, size_t len) {
    volatile uint8_t *p = (volatile uint8_t *)ptr;

    while (len-- != 0u) {
        *p++ = 0u;
    }

    /* Memory barrier so the clear completes before the function returns. */
    __asm__ __volatile__("" ::: "memory");
}
