/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Fuse secrets locking (C15 partial) and verification (C17).
//
// Locks read access to secret fuse fields via the SEP_EFUSE_MAP_LOCKS register.
// The LOCKS register is SET_ONLY: writing a 1 to a bit latches it permanently
// (until reset).  This prevents BL1 or later software from reading secret fuses.
//
// Secret fields: class_key, rma_sip_token_digest, rma_chiplet_token_digest.
// Locks and verifies secret-fuse read protection.

#include "fuse_lock.h"

#include "rom_mmio.h"
#include "sep.h"
#include "errors.h"
#include "rom_virt_console.h"

// Read-lock bits for secret fuse fields (all in low 32 bits of LOCKS register).
//
// The three UID fields are locked alongside the keys and tokens. A UID is not a
// secret in the same sense, but it is a stable per-part identifier that anything
// running after handoff can otherwise read directly out of the fuse block, so
// the ROM closes that window while it still owns the machine. All six fields
// declare the same properties in sep_efuse_map.rdl -- sw=rw, onwrite=woset,
// hw=r -- so they latch identically on the single SET_ONLY write below.
#define FUSE_SECRET_READ_LOCK_MASK \
    (SEP_EFUSE_MAP__LOCKS__CLASS_KEY_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__RMA_SIP_TOKEN_DIGEST_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__RMA_CHIPLET_TOKEN_DIGEST_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__CHIPLET_UID_READ_LOCK_bm | SEP_EFUSE_MAP__LOCKS__SIP_UID_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__SYS_UID_READ_LOCK_bm)

void lock_fuse_secrets(void) {
    // LOCKS register is SET_ONLY: writing 1 bits sets them, 0 bits are ignored.
    // No need to read-modify-write — just write the bits we want to set.
    mmio_write32(OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR, FUSE_SECRET_READ_LOCK_MASK);
}

bool check_fuse_secrets_locked(void) {
    uint32_t locks_lo = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR);
    bool locked = (locks_lo & FUSE_SECRET_READ_LOCK_MASK) == FUSE_SECRET_READ_LOCK_MASK;

    if (locked) {
        simputs("FUSE_SECRETS_LOCKED\n");
    } else {
        simputs("FUSE_SECRETS_NOT_LOCKED\n");
        simputshex32("LOCKS_LO=", locks_lo);
        simputshex32("EXPECTED=", FUSE_SECRET_READ_LOCK_MASK);
    }

    return locked;
}
