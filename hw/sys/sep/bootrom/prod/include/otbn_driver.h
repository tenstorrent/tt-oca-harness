/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OTBN hardware driver for OROM.
//
// Provides low-level access to the OpenTitan OTBN coprocessor for
// RSA-3072 modular exponentiation.  Ported from
// fw/sep/tests/otbn_rsa_3072_verify_test/otbn_rsa_3072_verify_test.c
// with ROM-appropriate error handling (no printf, bounded timeouts).

#pragma once

#include <stdint.h>

// OTBN status/error codes.
#define OTBN_OK 0
#define OTBN_ERR_TIMEOUT -1
#define OTBN_ERR_EXEC -2
#define OTBN_ERR_CRC -3
#define OTBN_ERR_NOT_IDLE -4
#define OTBN_ERR_NOT_STARTED -5

// Initialize OTBN: release from SW reset, zero DMEM.
// Returns OTBN_OK on success.
int otbn_init(void);

// Load the RSA-3072 OTBN application (IMEM + DMEM constants).
// Returns OTBN_OK on success, OTBN_ERR_CRC on checksum mismatch.
int otbn_load_rsa_app(void);

// Write word_count 32-bit words to OTBN DMEM starting at byte offset.
void otbn_dmem_write(uint32_t byte_offset, const uint32_t *data, uint32_t word_count);

// Read word_count 32-bit words from OTBN DMEM starting at byte offset.
void otbn_dmem_read(uint32_t byte_offset, uint32_t *data, uint32_t word_count);

// Execute the loaded OTBN program and wait for completion.
//
// Success means the program ran to completion: a command the block never
// accepted returns OTBN_ERR_NOT_STARTED rather than OTBN_OK, so a caller that
// gets OTBN_OK can trust that DMEM holds a computed result and not its own
// inputs.
//
// Returns OTBN_OK on success, or OTBN_ERR_TIMEOUT / OTBN_ERR_NOT_STARTED /
// OTBN_ERR_EXEC on failure.
int otbn_execute(void);
