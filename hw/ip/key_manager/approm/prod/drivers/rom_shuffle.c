/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_shuffle.c
 * @brief Fisher-Yates shuffle with bitmask rejection sampling
 */

#include "rom_shuffle.h"

/**
 * @brief Reset a bitpool to empty so the next draw refills from the PRNG.
 *
 * @param[in,out] pool Bitpool to reset.
 */
void rom_shuffle_init(rom_km_bitpool_t *pool) {
    pool->bits = 0;
    pool->remaining = 0;
}

/**
 * @brief Extract width bits from the pool, refilling from the PRNG as needed.
 *
 * @param[in,out] pool  Bitpool state.
 * @param[in]     prng  PRNG for refill.
 * @param[in]     width Number of bits to extract (1-32).
 * @return Extracted value.
 */
static uint32_t bitpool_draw(rom_km_bitpool_t *pool, rom_km_prng_state_t *prng, uint8_t width) {
    if (pool->remaining < width) {
        pool->bits = rom_prng_next(prng);
        pool->remaining = 32;
    }

    uint32_t val = pool->bits & ((1u << width) - 1);
    pool->bits >>= width;
    pool->remaining -= width;
    return val;
}

/**
 * @brief Minimum number of bits required to represent values in [0, bound).
 *
 * @param[in] bound Upper bound (exclusive); must be >= 1.
 * @return Bit width (0 if bound is 0 or 1).
 */
static uint8_t bit_width(uint16_t bound) {
    uint8_t w = 0;
    uint32_t v = (uint32_t)(bound - 1u);
    while (v) {
        v >>= 1;
        w++;
    }
    return w;
}

/**
 * @brief Draw a uniform random index in [0, bound) using bitmask rejection.
 *
 * @param[in,out] pool  Bitpool state (refilled from prng as needed).
 * @param[in]     prng  PRNG state for random bit generation.
 * @param[in]     bound Upper bound (exclusive); must be >= 1.
 * @return Random index in [0, bound).
 */
uint16_t rom_shuffle_index(rom_km_bitpool_t *pool, rom_km_prng_state_t *prng, uint16_t bound) {
    if (bound <= 1u) {
        return 0;
    }

    const uint8_t width = bit_width(bound);
    const uint32_t mask = (1u << width) - 1u;
    uint32_t candidate;

    do {
        candidate = bitpool_draw(pool, prng, width);
    } while (candidate >= (uint32_t)bound);

    return (uint16_t)(candidate & mask);
}

/**
 * @brief In-place Fisher-Yates shuffle of a uint16_t index array.
 *
 * @param[in,out] pool Bitpool state for random index generation.
 * @param[in]     prng PRNG state backing the bitpool.
 * @param[in,out] arr  Array to shuffle in place.
 * @param[in]     n    Number of elements in arr.
 */
void rom_shuffle_array(rom_km_bitpool_t *pool, rom_km_prng_state_t *prng, uint16_t *arr,
                       uint16_t n) {
    for (uint16_t i = (uint16_t)(n - 1u); i > 0u; i--) {
        uint16_t j = rom_shuffle_index(pool, prng, (uint16_t)(i + 1u));
        uint16_t tmp = arr[i];
        arr[i] = arr[j];
        arr[j] = tmp;
    }
}

/**
 * @brief Initialise an index array to [0..n) and shuffle it in place.
 *
 * Convenience wrapper combining identity initialisation, bitpool reset, and
 * Fisher-Yates shuffle into a single call.
 *
 * @param[in]     prng PRNG state for random index generation.
 * @param[out]    arr  Array to fill with shuffled indices (must hold n elements).
 * @param[in]     n    Number of elements.
 */
void rom_shuffle_init_array(rom_km_prng_state_t *prng, uint16_t *arr, uint16_t n) {
    for (uint16_t i = 0; i < n; i++) arr[i] = i;

    rom_km_bitpool_t pool;
    rom_shuffle_init(&pool);
    rom_shuffle_array(&pool, prng, arr, n);
}
