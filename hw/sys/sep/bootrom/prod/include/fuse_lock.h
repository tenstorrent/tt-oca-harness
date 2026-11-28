/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Fuse secrets locking API ([S25] partial / [S26]).
//
// lock_fuse_secrets():          Write read-lock bits for secret fuse fields.
// check_fuse_secrets_locked():  Verify read-lock bits are set (defensive check).
//
// Fields locked: class_key, rma_sip_token_digest, rma_chiplet_token_digest,
// chiplet_uid, sip_uid, sys_uid.
// Uses the SET_ONLY LOCKS register — once locked, cannot be unlocked until reset.

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "sep.h"

// Read-lock bits for secret fuse fields (all in low 32 bits of LOCKS register).
//
// All six are secrets. A UID is the per-device secret seed the Key Manager
// derives keys from, so a UID that leaks compromises every key derived from it.
// UIDs are not identifiers: the non-secret per-part identifiers are the ID
// fuses (chiplet_id / sip_id / system_id), which are not locked here. All six fields
// declare the same properties in sep_efuse_map.rdl -- sw=rw, onwrite=woset,
// hw=r -- so they latch identically on the single SET_ONLY write of lock_fuse_secrets().
#define FUSE_SECRET_READ_LOCK_MASK \
    (SEP_EFUSE_MAP__LOCKS__CLASS_KEY_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__RMA_SIP_TOKEN_DIGEST_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__RMA_CHIPLET_TOKEN_DIGEST_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__CHIPLET_UID_READ_LOCK_bm | SEP_EFUSE_MAP__LOCKS__SIP_UID_READ_LOCK_bm | \
     SEP_EFUSE_MAP__LOCKS__SYS_UID_READ_LOCK_bm)

// Set the read-lock bits for all six protected fuse fields.
// Writes read_lock bits in SEP_EFUSE_MAP_LOCKS register (SET_ONLY: irreversible).
void lock_fuse_secrets(void);

// Verify that all secret fuse read_lock bits are set.
// Returns true if all secrets are locked, false otherwise.
bool check_fuse_secrets_locked(void);
