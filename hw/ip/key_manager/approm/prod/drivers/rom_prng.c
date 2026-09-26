/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_prng.c
 * @brief xoshiro128++ PRNG implementation
 *
 * Reference: Blackman & Vigna, "Scrambled Linear Pseudorandom Number
 * Generators", ACM Trans. Math. Softw. 2021.
 */

#include "rom_prng.h"

/**
 * @brief 32-bit left rotation (xoshiro128++ helper).
 *
 * @param[in] x Value to rotate.
 * @param[in] k Number of bits to rotate left (0-31).
 * @return Rotated value.
 */
uint32_t rom_rotl32(uint32_t x, int k) {
    return (x << k) | (x >> (32 - k));
}

/**
 * @brief Seed the PRNG from the DRBG (four 32-bit words).
 *
 * Escapes the all-zero state if DRBG returns zeros.
 *
 * @param[in,out] state PRNG state to seed.
 */
void rom_prng_seed(rom_km_prng_state_t *state) {
    state->s[0] = rom_drbg_get_word();
    state->s[1] = rom_drbg_get_word();
    state->s[2] = rom_drbg_get_word();
    state->s[3] = rom_drbg_get_word();

    /* All-zero state is an absorbing fixed point for xoshiro; escape it. */
    if ((state->s[0] | state->s[1] | state->s[2] | state->s[3]) == 0) {
        state->s[0] = 1;
    }
}

/**
 * @brief Advance the PRNG and return the next 32-bit value (xoshiro128++).
 *
 * @param[in,out] state PRNG state.
 * @return Next pseudorandom 32-bit value.
 */
uint32_t rom_prng_next(rom_km_prng_state_t *state) {
    const uint32_t result = rom_rotl32(state->s[0] + state->s[3], 7) + state->s[0];
    const uint32_t t = state->s[1] << 9;

    state->s[2] ^= state->s[0];
    state->s[3] ^= state->s[1];
    state->s[1] ^= state->s[2];
    state->s[0] ^= state->s[3];
    state->s[2] ^= t;
    state->s[3] = rom_rotl32(state->s[3], 11);

    return result;
}
