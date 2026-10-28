/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Steps of abr_mldsa87_verify(), exposed for tests that need to stop the sequence
// part-way, such as zeroizing in the middle of a stream. They exist as functions
// only in a build that defines ABR_DRV_EXPOSE_STEPS; production code calls
// abr_mldsa87_verify() only.

#ifndef ABR_DRIVER_INTERNAL_H
#define ABR_DRIVER_INTERNAL_H

#include <stdint.h>

#include "abr_driver.h"

#define ABR_DRV_CTILDE_WORDS (ABR_MLDSA87_CTILDE_BYTES / 4u)

typedef struct {
    uint32_t ct[ABR_DRV_CTILDE_WORDS]; // c~ copied once from the caller's signature
    uint32_t written;                  // message bytes written to MSG
    uint32_t written_dup;              // the same count, kept separately
    uint32_t streaming;                // 1 once MSG_STREAM_READY has been seen
    uint32_t open_checks;              // stream-still-open checks passed before the end
    abr_drv_diag_t diag;
} abr_drv_ctx_t;

#ifdef ABR_DRV_EXPOSE_STEPS
// Zero every field, as abr_mldsa87_verify() does before its first step.
void abr_drv_ctx_init(abr_drv_ctx_t *ctx);

// Copy c~ out of signature, check the accelerator's identity, zeroize, then load
// PUBKEY, SIGNATURE and an empty context. Rejects an all-zero or all-ones c~ before
// touching the accelerator.
int abr_drv_load(abr_drv_ctx_t *ctx, const uint8_t *public_key, const uint8_t *signature);

// Clear the command-done and internal-error events and their counters, issue
// VERIFY | STREAM_MSG and require VERIFY_RES to read ~c~.
int abr_drv_start(abr_drv_ctx_t *ctx);

// Stream len bytes of message. The first call waits for MSG_STREAM_READY. Unless
// final is set, len must be a multiple of four; a final call checks the stream is
// still open, then ends it.
int abr_drv_stream_range(abr_drv_ctx_t *ctx, const uint8_t *message, uint32_t len, int final);

// Wait for VALID, require exactly one command-done event and no internal error, check
// the PUBKEY and c~ read-back, decide the verdict and zeroize.
int abr_drv_finish(abr_drv_ctx_t *ctx, const uint8_t *public_key, uint32_t message_len,
                   uint32_t pass_token, uint32_t *verdict);
#endif

#endif // ABR_DRIVER_INTERNAL_H
