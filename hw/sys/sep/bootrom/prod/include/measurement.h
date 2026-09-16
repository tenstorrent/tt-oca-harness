/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// BL0 boot measurement.
//
// Records the boot state so a later stage or a remote verifier can tell a
// trusted boot from a downgraded one. The measurement is a report only: no key
// material is bound to it, so a downgraded boot is detectable but not
// cryptographically prevented.
//
// Runs after the demotion register write. None of the inputs is a secret, so it
// does not need to precede lock_fuse_secrets().
//
// The input layout is byte-for-byte the layout a verifier outside this ROM
// expects, so a padding or ordering change here produces a digest nobody else
// can reproduce:
//
//     uint8_t  manifest_hash[32];
//     uint32_t lc_state;           // masked to 4 bits
//     uint32_t demotion_decision;  // masked to 3 bits
//     uint32_t secure_boot;        // masked to 1 bit
//     uint32_t sboot_dis;          // masked to 1 bit
//
// 48 bytes, each scalar a full little-endian word with the unused high bits
// zero. The masks matter: an unmasked lc_state would let a bit outside the state
// field change the digest.
//
// Only the digest is stored. Keeping the raw inputs in bl0_state as well would
// need 48 more bytes, and the struct plus that block exceeds the DCCM reserve.

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "errors.h"
#include "hmac_sha256.h"
#include "rom_virt_console.h"
#include "status_values.h"

struct rom_measurement_input {
    uint8_t manifest_hash[SHA256_DIGEST_SIZE_BYTES];
    uint32_t lc_state;
    uint32_t demotion_decision;
    uint32_t secure_boot;
    uint32_t sboot_dis;
};

_Static_assert(sizeof(struct rom_measurement_input) == 48,
               "measurement input must stay 48 bytes: 32-byte hash plus four "
               "little-endian words. A padding change here produces a digest no "
               "verifier can reproduce.");

// Compute the boot measurement and store it in bl0_state.
//
// demotion_bits packing:
//   bit 0 = the flag that made the demotion decision
//   bit 1 = lock_demotion
//   bit 2 = bl2_demotion_decision
//
// Returns 0 on success, 1 on a crypto engine failure; the caller maps that onto
// an error code.
static inline uint32_t rom_record_measurement(const uint8_t *manifest_hash, uint32_t demotion_bits,
                                              bool secure_boot, uint32_t lc_state, bool sboot_dis) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_RECORD_MEASUREMENT);

    struct rom_measurement_input input;
    for (uint32_t i = 0; i < SHA256_DIGEST_SIZE_BYTES; ++i) {
        input.manifest_hash[i] = manifest_hash[i];
    }
    input.lc_state = lc_state & 0xFu;
    input.demotion_decision = demotion_bits & 0x7u;
    input.secure_boot = secure_boot ? 1u : 0u;
    input.sboot_dis = sboot_dis ? 1u : 0u;

    simputshex32("MEAS_LC=", input.lc_state);
    simputshex32("MEAS_DEMOTE=", input.demotion_decision);
    simputshex32("MEAS_SBOOT=", input.secure_boot);
    simputshex32("MEAS_SBOOT_DIS=", input.sboot_dis);

    uint8_t digest[SHA256_DIGEST_SIZE_BYTES];
    if (sha256((const uint8_t *)&input, (uint32_t)sizeof(input), digest) != 0) {
        simputs("MEASUREMENT_FAIL\n");
        return 1u;
    }

    struct bl0_state *s = get_bl0_state();
    for (uint32_t i = 0; i < SHA256_DIGEST_SIZE_BYTES; ++i) {
        s->measurement[i] = digest[i];
    }

    // The first word is emitted so a run can be identified from the status ring
    // alone; the full digest is in bl0_state for BL1.
    uint32_t first = ((uint32_t)digest[0]) | ((uint32_t)digest[1] << 8) |
                     ((uint32_t)digest[2] << 16) | ((uint32_t)digest[3] << 24);
    simputshex32("MEASUREMENT=", first);
    simputs("MEASUREMENT_OK\n");
    return 0u;
}
