/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file rom_secutil.h
 * @brief Side-channel- and fault-hardened memory helpers.
 *
 * Helpers to clear sensitive material and to compare secrets without leaking
 * timing or being trivially glitched.
 */

#ifndef ROM_SECUTIL_H
#define ROM_SECUTIL_H

#include <stddef.h>

/**
 * @brief Constant-time, glitch-aware memory comparison.
 *
 * Compares two buffers in constant time to avoid timing side-channels, and
 * cross-checks the loop iteration count against @p num so a glitch that skips
 * iterations is detected. Returns only 0 or 1 so the result never leaks which
 * bytes differed.
 *
 * @param ptr1 First buffer.
 * @param ptr2 Second buffer.
 * @param num  Number of bytes to compare.
 * @return 0 if all bytes are equal and the loop ran to completion,
 *         1 if any byte differs or a glitch is detected.
 */
int rom_const_time_memcmp(const void *ptr1, const void *ptr2, size_t num);

/**
 * @brief Constant-time pointer-equality check for glitch detection.
 *
 * @param ptr1 First pointer.
 * @param ptr2 Second pointer.
 * @return 1 if the pointers are equal (glitch suspected), 0 if different.
 */
int rom_pointers_are_equal_ct(const void *ptr1, const void *ptr2);

/**
 * @brief Clear memory without being optimized away.
 *
 * Uses a volatile pointer and a compiler memory barrier so the clear is not
 * elided when the buffer is dead afterwards.
 *
 * @param ptr Buffer to clear.
 * @param len Number of bytes to clear.
 */
void rom_secure_memzero(void *ptr, size_t len);

#endif /* ROM_SECUTIL_H */
