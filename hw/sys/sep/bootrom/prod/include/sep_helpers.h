/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Helper utilities for OCAH SEP bootcode.
//
// Freestanding (no libc) helper routines for range checks and explicit clearing.

#ifndef __SEP_HELPERS_H_DEFINED__
#define __SEP_HELPERS_H_DEFINED__

#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

/**
 * Check if two address ranges overlap.
 *
 * @param r1_start Start address of range 1
 * @param r1_size Size of range 1
 * @param r2_start Start address of range 2
 * @param r2_size Size of range 2
 *
 * @return 0 if ranges don't overlap, 1 if they do, or negative if invalid.
 */
static inline int ranges_overlap(size_t r1_start, size_t r1_size, size_t r2_start, size_t r2_size) {
    // Empty ranges: treat as error (probably indicates a bug elsewhere).
    if (r1_size == 0 || r2_size == 0) return -1;

    // Calculate inclusive end of ranges
    size_t r1_end = r1_start + r1_size - 1;
    size_t r2_end = r2_start + r2_size - 1;

    // Check for overflow
    if (r1_end < r1_start || r2_end < r2_start) return -2;

    if ((r1_start <= r2_end) && (r1_end >= r2_start)) return 1;

    return 0;
}

/**
 * Zero out a memory region (compiler barrier prevents elision).
 */
static inline void explicit_memzero(uint8_t *p, size_t size) {
    for (size_t i = 0; i < size; ++i) p[i] = 0;
    __asm__ volatile("" ::: "memory");
}

/**
 * Check if one range contains another.
 *
 * @return True if the outer range fully contains the inner range.
 */
static inline bool contains_range(size_t outer_start, size_t outer_size, size_t inner_start,
                                  size_t inner_size) {
    if (outer_size == 0 || inner_size == 0) return false;

    size_t outer_end = outer_start + outer_size - 1;
    size_t inner_end = inner_start + inner_size - 1;

    // Overflow check
    if (outer_end < outer_start || inner_end < inner_start) return false;

    if (outer_start > inner_start) return false;

    if (outer_end < inner_end) return false;

    return true;
}

#endif // __SEP_HELPERS_H_DEFINED__
