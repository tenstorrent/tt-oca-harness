// Fuse secrets locking API (C15 partial / C17).
//
// lock_fuse_secrets():          Write read-lock bits for secret fuse fields.
// check_fuse_secrets_locked():  Verify read-lock bits are set (defensive check).
//
// Secret fields locked: class_key, rma_sip_token, rma_chiplet_token.
// Uses the SET_ONLY LOCKS register — once locked, cannot be unlocked until reset.

#pragma once

#include <stdbool.h>
#include <stdint.h>

// Lock secret fuse fields (class_key, rma_sip_token, rma_chiplet_token).
// Writes read_lock bits in SEP_EFUSE_MAP_LOCKS register (SET_ONLY: irreversible).
void lock_fuse_secrets(void);

// Verify that all secret fuse read_lock bits are set.
// Returns true if all secrets are locked, false otherwise.
bool check_fuse_secrets_locked(void);
