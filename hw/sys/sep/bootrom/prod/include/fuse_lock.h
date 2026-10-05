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

// Set the read-lock bits for all six protected fuse fields.
// Writes read_lock bits in SEP_EFUSE_MAP_LOCKS register (SET_ONLY: irreversible).
void lock_fuse_secrets(void);

// Verify that all secret fuse read_lock bits are set.
// Returns true if all secrets are locked, false otherwise.
bool check_fuse_secrets_locked(void);
