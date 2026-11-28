/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Pre-hand-off gate ledger and self-check (rom.adoc, SEP-ROM-HOFF-040/-050).

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "harden.h"

#define BOOT_GATE_MANIFEST 0x1u
#define BOOT_GATE_CRYPTO 0x2u
#define BOOT_GATE_HASH 0x4u
#define BOOT_GATE_FUSELOCK 0x8u
#define BOOT_GATE_EXPECT \
    (BOOT_GATE_MANIFEST | BOOT_GATE_CRYPTO | BOOT_GATE_HASH | BOOT_GATE_FUSELOCK)

// Starts a manifest slot attempt with no gate passed and no manifest length recorded.
void gate_ledger_reset(void);

// One function per gate, so each stamp has its own call site and its own stores.
void gate_stamp_manifest(void);
void gate_stamp_crypto(void);
void gate_stamp_hash(void);
void gate_stamp_fuselock(void);

// Validated manifest body length, for the manifest-locus bound of the self-check.
void gate_ledger_record_manifest_len(uint32_t len);

// Returns only when every check passes; any failure halts with
// ROM_ERR_HANDOFF_SELFCHECK_FAILED.
void rom_handoff_selfcheck(void);

// A stamp decision on a status that must be zero. Both evaluations and both of their
// results are laundered, so the compiler can neither fold an evaluation into an
// earlier test of the status nor merge the two compares into one.
static inline bool gate_status_ok(uint32_t status) {
    const uint32_t first = harden_u32(harden_u32(status) == 0u);
    const uint32_t second = harden_u32(harden_u32(status) == 0u);
    return (first & second) != 0u;
}
