/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_shuffle.h
 * @brief Fisher-Yates shuffle with bitmask rejection sampling
 *
 * Provides an unbiased shuffle for uint16_t index arrays using a bit pool
 * fed by the xoshiro128++ PRNG.  Used to randomise the write order
 * when loading key material into crypto-engine sideload registers and
 * during shred passes (e.g. KPV slots, engine key regions).
 */

#ifndef ROM_SHUFFLE_H
#define ROM_SHUFFLE_H

#include <stdint.h>
#include "rom_prng.h"

/*===========================================================================
 * Types
 *===========================================================================*/

/**
 * @brief Bit pool for dispensing variable-width random bit fields
 *
 * Accumulates 32 bits at a time from the PRNG and hands them out in
 * chunks sized to the requested bound, avoiding repeated full-word
 * PRNG calls for small index ranges.
 */
typedef struct {
    uint32_t bits;     /**< Buffered random bits */
    uint8_t remaining; /**< Number of valid bits left in @c bits */
} rom_km_bitpool_t;

/*===========================================================================
 * Public API
 *===========================================================================*/

/**
 * @brief Reset the bit pool to empty
 *
 * Must be called before the first use of rom_shuffle_index() with a
 * given pool instance.
 *
 * @param pool Bit pool to initialise.
 */
void rom_shuffle_init(rom_km_bitpool_t *pool);

/**
 * @brief Draw a uniform random index in [0, bound).
 *
 * Uses bitmask rejection sampling: computes the smallest power-of-two
 * mask that covers bound, extracts that many bits from the pool,
 * and rejects candidates >= bound.  Bits are consumed from the
 * pool LSB-first; when the pool is exhausted it is refilled from prng.
 *
 * @param pool Bit pool (may be refilled).
 * @param prng PRNG state used to refill the pool.
 * @param bound Exclusive upper bound (must be >= 1, up to 65535).
 * @return Random value in [0, bound).
 */
uint16_t rom_shuffle_index(rom_km_bitpool_t *pool, rom_km_prng_state_t *prng, uint16_t bound);

/**
 * @brief In-place Fisher-Yates shuffle of a uint16_t index array.
 *
 * Iterates from the last element down to the second, swapping each
 * with a uniformly chosen earlier (or same) element.  Supports n up to 65535
 * (uint16_t range; e.g. 512 for full KPV key array).
 *
 * @param pool Bit pool for random index generation.
 * @param prng PRNG state.
 * @param arr Array of indices to shuffle.
 * @param n Number of elements in arr.
 */
void rom_shuffle_array(rom_km_bitpool_t *pool, rom_km_prng_state_t *prng, uint16_t *arr,
                       uint16_t n);

/**
 * @brief Initialise an index array to [0..n) and shuffle it in place.
 *
 * Convenience wrapper combining identity initialisation, bitpool reset, and
 * Fisher-Yates shuffle into a single call.
 *
 * @param prng PRNG state for random index generation.
 * @param arr Array to fill with shuffled indices (must hold n elements).
 * @param n Number of elements.
 */
void rom_shuffle_init_array(rom_km_prng_state_t *prng, uint16_t *arr, uint16_t n);

#endif /* ROM_SHUFFLE_H */
