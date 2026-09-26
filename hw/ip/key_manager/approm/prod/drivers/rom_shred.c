/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_shred.c
 * @brief Generic shred implementation for contiguous word regions.
 */

#include "rom_shred.h"
#include "rom_defs.h"
#include "rom_msg_tx.h"
#include "rom_picorv32.h"
#include "rom_prng.h"
#include "rom_shuffle.h"

/**
 * @brief Shuffle-order scratch for rom_shred_region.
 */
static uint16_t rom_shred_order[ROM_KM_KPV_TOTAL_WORDS];

/**
 * @brief Shred a memory region with PRNG data in shuffled word order.
 *
 * Overwrites @p word_count words starting at @p base in a pseudorandom
 * permutation of word indices for ROM_KM_SHRED_ITER+1 passes.  When @p
 * allow_reseed is non-zero, the PRNG is reseeded from the DRBG before each
 * pass; when zero (e.g. wipe path), the PRNG is not reseeded.
 *
 * @param[in]     base        Base address of the region (32-bit aligned).
 * @param[in]     word_count  Number of 32-bit words to shred.
 * @param[in,out] prng        PRNG state; reseeded each pass iff allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed from DRBG each pass; 0 for
 *                             wipe path (no DRBG access).
 */
void rom_shred_region(volatile uint32_t *base, uint16_t word_count, rom_km_prng_state_t *prng,
                      uint8_t allow_reseed) {
    /* word_count must never exceed the static shred-order buffer.  All callers
     * pass compile-time-bounded counts, so this can only trip on a firmware bug
     * or memory corruption.  Fail closed: silently returning would both skip
     * shredding key material and risk an out-of-bounds write in
     * rom_shuffle_init_array() below.  Report the fault and halt directly rather
     * than calling rom_trigger_unrecoverable(), because that path itself shreds
     * the crypto-engine keys via rom_shred_region() — re-entering here would
     * recurse.  The CPU halt also asserts the unrecoverable-fault signal to the
     * SEP. */
    if (word_count > ROM_KM_KPV_TOTAL_WORDS) {
        uint32_t fault = (uint32_t)(int32_t)ROM_KM_UFAULT_SHRED_RANGE;
        rom_msg_tx_send_direct(ROM_KM_RESP_UNRECOVERABLE_FAULT, &fault, 1);
        rom_picorv32_halt_trap();
    }

    uint16_t *order = rom_shred_order;

    for (uint8_t pass = 0; pass < ROM_KM_SHRED_ITER + 1; pass++) {
        if (allow_reseed) rom_prng_seed(prng);

        rom_shuffle_init_array(prng, order, word_count);

        for (uint16_t j = 0u; j < word_count; j++) {
            uint16_t idx = order[j];
            base[idx] = rom_prng_next(prng);
        }
    }
}
