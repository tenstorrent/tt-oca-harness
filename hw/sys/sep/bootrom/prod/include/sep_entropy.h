/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP entropy chain bring-up (ESRC -> DRBG/CSRNG -> EDN) for the boot ROM.
//
// Several crypto blocks (OTBN and AES) the ROM drives do not work without it.
// OTBN parks in its URND reseed state and never executes; the AES masking
// PRNG never reports STATUS.IDLE. Neither is hardware auto-initialisation:
// every stage of the chain is disabled at reset and be initialized by BL0.
//
// Scope: the INTERNAL entropy source only. Selecting an external TRNG is a
// stub here on purpose -- see sep_entropy_select_external_source().

#pragma once

#include <stdbool.h>

// Bring up the entropy chain, once per boot.
//
// Takes the internal ESRC -> CSRNG -> EDN chain, or the external-TRNG seam
// below if this build overrides the source selection.
//
// Idempotent: the first call performs the sequence and records the outcome,
// later calls return that same outcome without touching hardware. Safe to call
// from every crypto init that needs entropy.
//
// Returns 0 on success. DOES NOT RETURN on failure: a failed entropy bring-up
// stops secure boot, reported as SEP_MSG_ENTROPY_INIT_FAILED with a console
// marker naming the stage that failed. That is deliberate -- it is a
// device-level failure, so the backup manifest slot carries the same crypto
// requirement and rotating to it cannot help, while letting the failure surface
// as a signature error would report the wrong cause. Callers therefore need no
// return check.
int sep_entropy_init(void);

// --- adopter seam: switching RNG source -----------------------------------
//
// This harness is the test vehicle for the OCAH INTERNAL entropy source, so the
// internal chain is what sep_entropy_init() brings up. An adopter taping this
// design out is expected to use a qualified external TRNG instead, and should be
// able to switch without touching the boot flow.
//
// Both hooks below are WEAK, so a build that carries an external-TRNG driver
// overrides them at link time through the Makefile's NONFREE_BOOTCODE_SOURCES
// hook -- the same weak-stub/strong-override pattern src/sep_spi.c uses for the
// SPI controller. Overriding these two functions is the whole switch: neither
// sep_entropy_init()'s callers nor any other part of the ROM changes.

// Which source this build uses. Weak; returns true here (internal chain).
// Override returning false to take the external path.
bool sep_entropy_use_internal_source(void);

// Bring up and validate an external TRNG. Weak; a stub in this tree that fails,
// because the external TRNG is third-party commercial IP that does not ship in
// this design.
//
// An override must leave EXT_TRNG_SRC_SEL.sel[1] SET -- its reset value, so the
// crypto-block stream keeps taking the external source -- initialise the device
// through its own control interface, and return 0 only once it is producing
// entropy. Returning 0 without a working source hands the crypto blocks a dead
// stream, which stalls them exactly as an unconfigured chain would.
int sep_entropy_bringup_external(void);
