/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP platform binding for the OCA boot-manifest validation library.
//
// The library ships no hardware access of its own: it takes a table of function
// pointers and calls back into the integrator for hashing, signature checks,
// payload decryption and OTP reads. This header exposes the one table the ROM
// populates. See tools/tt-oca-manifest/validators/oca/INTEGRATION.md.

#pragma once

#include "oca_validator.h"

// The SEP callback table. Statically initialised, no setup call required.
//
// Never NULL, but individual entries are: an unwired callback is a legal state
// that makes the check needing it fail with OCA_FAIL_CALLBACK_UNAVAILABLE, which
// is why this returns a table rather than reporting readiness. The set_* entries
// are deliberately unwired -- see oca_platform.c.
const oca_callbacks_t *sep_oca_callbacks(void);
