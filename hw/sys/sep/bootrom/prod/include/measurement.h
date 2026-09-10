/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Soft measurement enrollment (PCRV forerunner).
//
// The roadmap adds a Platform Configuration Registers Vault (PCRV) to the Key
// Manager IP: software registers measurement records, the PCRV hashes them
// internally into an incrementing, software-tamper-proof register bank cleared
// only on cold reset.  Until that hardware exists, BL0 implements the same
// enrollment model in software ("soft PCRs") and stores the results in
// bl0_state; BL1 registers them into the PCRV once it exists.
//
// Extend semantics (aligned with the intended PCRV behavior; provisional until
// the PCRV interface is ratified):
//   soft_pcr[slot] = SHA256( soft_pcr[slot] || SHA256(record) )
// with soft_pcr[slot] starting as 32 zero bytes (init_bl0_state()).
//
// BL0 enrolls exactly two records:
//   MEAS_SLOT_ROM        (future PCR[0]): the 32-byte ROM self-hash, verified
//       at boot by recomputing SHA-256 over the hashed ROM region and
//       comparing against the build-time embedded value.
//   MEAS_SLOT_BOOT_STATE (future PCR[1]): the boot-state record -- verified
//       manifest hash plus device state (LC state, secure boot, SBOOT_DIS,
//       demotion).

#pragma once

#include <stdint.h>

#include "bl0_state.h"

// Demotion bits recorded in the boot-state record (and bl0_state).
#define MEAS_DEMOTION_BL1_DEMOTE (1u << 0)   // DEMOTE_1 state applied by BL0
#define MEAS_DEMOTION_BL1_LOCKED (1u << 1)   // DEMOTE_1 locked by BL0
#define MEAS_DEMOTION_BL2_DECISION (1u << 2) // recorded BL2 demotion decision

// Enroll a measurement record into a soft-PCR slot (extend semantics above).
// Returns 0 on success, non-zero on invalid slot or hash-engine error.
uint32_t measurement_enroll(uint32_t slot, const uint8_t *record, uint32_t len);

// Verify the build-time embedded ROM hash (g_rom_sha256_str) by recomputing
// SHA-256 over the hashed ROM region ([OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR,
// __metadata_end) -- the .text + .metadata bytes hashed by
// tools/insert-rom-sha256.py), then enroll the verified hash in MEAS_SLOT_ROM
// and record the raw value in bl0_state.rom_hash.
// Returns 0 on success; non-zero on parse failure, hash-engine error, or a
// recompute mismatch (callers treat all of these as fatal).
uint32_t measurement_enroll_rom_hash(void);

// Compose the boot-state record from the validated manifest hash, the device
// state already captured in bl0_state (lc_state / secure_boot / sboot_dis),
// and the demotion bits (MEAS_DEMOTION_*); enroll it in MEAS_SLOT_BOOT_STATE
// and store the raw record in bl0_state.meas_boot_record for BL1.
// Returns 0 on success, non-zero on hash-engine error.
uint32_t measurement_enroll_boot_state(const uint8_t manifest_hash[32], uint8_t demotion_bits);
