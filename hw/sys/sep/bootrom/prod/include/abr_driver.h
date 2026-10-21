/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Adams Bridge (ABR) ML-DSA-87 signature verification.
//
// Verifies a pure ML-DSA-87 signature (FIPS 204 ML-DSA.Verify, empty context, no
// pre-hash) over a message streamed to the accelerator. The verdict is bound to what
// the accelerator latched: the challenge it preloaded, the key and challenge it read
// back, the bytes it was streamed and the single completion it reported.
//
// Caller preconditions:
//   - public_key, signature and message are in SEP-private memory that no DMA engine,
//     SMC or host master can write for the duration of the call.
//   - public_key is already authenticated against a trust anchor and is the same copy
//     that was hashed for that check.
//   - The bytes streamed are the only bytes verified; use the same buffer afterwards.
//   - message_len does not come from unauthenticated data: a skipped MSG store
//     drops a word undetected, which is harmless only when the length is fixed.
//   - pass_token is not 0, 0xFFFFFFFF or 0xC3A5965A (the driver's verdict key).
//   - Nothing else uses the accelerator during the call.

#ifndef ABR_DRIVER_H
#define ABR_DRIVER_H

#include <stdint.h>

#define ABR_DRV_OK 0
#define ABR_DRV_ERR_PARAM (-1)
#define ABR_DRV_ERR_TIMEOUT (-2)
#define ABR_DRV_ERR_HW (-3) // STATUS.ERROR or an internal-error event
#define ABR_DRV_ERR_SIG_INVALID (-4)
#define ABR_DRV_ERR_IDENTITY (-5)
#define ABR_DRV_ERR_FAULT (-6) // redundant checks disagree, or a readback mismatch
#define ABR_DRV_ERR_STATE (-7) // the accelerator is not in the state it must be in

#define ABR_MLDSA87_PK_BYTES 2592u
#define ABR_MLDSA87_SIG_BYTES 4627u
#define ABR_MLDSA87_CTILDE_BYTES 64u
#define ABR_MLDSA87_MAX_MSG_BYTES 65536u

// Where a call ended; for diagnostics only.
typedef enum {
    ABR_DRV_STAGE_ARGS,
    ABR_DRV_STAGE_ZEROIZE,
    ABR_DRV_STAGE_ARM,
    ABR_DRV_STAGE_LOAD,
    ABR_DRV_STAGE_START,
    ABR_DRV_STAGE_PRELOAD,
    ABR_DRV_STAGE_STREAM_WAIT,
    ABR_DRV_STAGE_STREAM,
    ABR_DRV_STAGE_COMPLETE,
    ABR_DRV_STAGE_READBACK,
    ABR_DRV_STAGE_VERDICT,
    ABR_DRV_STAGE_DONE
} abr_drv_stage_e;

typedef struct {
    uint32_t bytes_written; // message bytes written to MSG
    uint32_t early_valid;   // 1 if VALID rose before MSG_STREAM_READY
    uint32_t res_inverse;   // 1 if VERIFY_RES equalled ~c~ at completion
    uint32_t res_nonzero;   // 1 if VERIFY_RES was not all-zero at completion
    uint32_t done_count;    // command-done events the accelerator counted
    uint32_t stage;         // abr_drv_stage_e
} abr_drv_diag_t;

// Check the ML-DSA name and version registers. ABR_DRV_OK or ABR_DRV_ERR_IDENTITY.
int abr_drv_check_identity(void);

// Zeroize the accelerator and wait for STATUS to read READY alone.
int abr_drv_zeroize(void);

// Verify signature over message_len bytes of message under public_key.
//
// The signature is valid only when the return value is ABR_DRV_OK and *verdict equals
// pass_token; every other outcome writes ~pass_token. Compare *verdict, not just the
// return value: the verdict is the hardened result. diag may be NULL.
int abr_mldsa87_verify(const uint8_t *public_key, const uint8_t *signature, const uint8_t *message,
                       uint32_t message_len, uint32_t pass_token, uint32_t *verdict,
                       abr_drv_diag_t *diag);

#endif // ABR_DRIVER_H
