/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_shred.h
 * @brief Generic shred library for overwriting memory with PRNG data
 *
 * Overwrites a contiguous region of 32-bit words with PRNG-sourced data in
 * shuffled write order for ROM_KM_SHRED_ITER+1 passes.  Supports an option to
 * disable DRBG reseed per pass for use in the wipe-state path (spec: no DRBG
 * access during wipe to avoid hangs).
 */

#ifndef ROM_SHRED_H
#define ROM_SHRED_H

#include <stdint.h>
#include "rom_defs.h"
#include "rom_prng.h"

/**
 * @brief Shred a memory region with PRNG data in shuffled word order.
 *
 * Overwrites @p word_count words starting at @p base in a pseudorandom
 * permutation of word indices for ROM_KM_SHRED_ITER+1 passes.  When @p
 * allow_reseed is non-zero, the PRNG is reseeded from the DRBG before each
 * pass; when zero (e.g. wipe path), the PRNG is not reseeded.
 *
 * @param base Base address of the region (32-bit aligned).
 * @param word_count Number of 32-bit words to shred.
 * @param prng PRNG state; reseeded each pass iff allow_reseed.
 * @param allow_reseed Non-zero to reseed from DRBG each pass; 0 for
 *     wipe path (no DRBG access).
 */
void rom_shred_region(volatile uint32_t *base, uint16_t word_count, rom_km_prng_state_t *prng,
                      uint8_t allow_reseed);

#endif /* ROM_SHRED_H */
