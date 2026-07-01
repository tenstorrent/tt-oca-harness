/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_prng.h
 * @brief xoshiro128++ pseudo-random number generator for Key Manager firmware
 *
 * Provides a fast, small-state PRNG seeded from the hardware DRBG.
 * Used for shred patterns, Fisher-Yates shuffling of write order,
 * and other non-cryptographic randomisation within the firmware.
 */

#ifndef ROM_PRNG_H
#define ROM_PRNG_H

#include <stdint.h>
#include "rom_drbg.h"

/*===========================================================================
 * Types
 *===========================================================================*/

/** @brief xoshiro128++ generator state (128 bits) */
typedef struct {
    uint32_t s[4];
} rom_km_prng_state_t;

/*===========================================================================
 * Helpers
 *===========================================================================*/

/**
 * @brief 32-bit left rotation (xoshiro128++ helper).
 *
 * @param x Value to rotate.
 * @param k Number of bits to rotate left (0-31).
 * @return Rotated value.
 */
uint32_t rom_rotl32(uint32_t x, int k);

/*===========================================================================
 * Public API
 *===========================================================================*/

/**
 * @brief Seed the PRNG state from the hardware DRBG
 *
 * Reads four 32-bit words via rom_drbg_get_word(). If the DRBG
 * returns an all-zero seed (degenerate absorbing state for xoshiro),
 * s[0] is forced to 1 so the generator remains functional.
 *
 * @param state PRNG state to initialise.
 */
void rom_prng_seed(rom_km_prng_state_t *state);

/**
 * @brief Generate the next 32-bit pseudo-random value.
 *
 * Implements the xoshiro128++ output function and advances the
 * internal state by one step.
 *
 * @param state PRNG state (must have been seeded).
 * @return 32-bit pseudo-random value.
 */
uint32_t rom_prng_next(rom_km_prng_state_t *state);

#endif /* ROM_PRNG_H */
