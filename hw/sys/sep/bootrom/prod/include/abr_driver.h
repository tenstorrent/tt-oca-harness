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
//   - message_len does not come from unauthenticated data: a skipped MSG store or
//     a corrupted last strobe changes the verified length by less than four bytes
//     undetected, which is harmless only when the length is fixed.
//   - pass_token is not 0, 0xFFFFFFFF or ABR_DRV_VERDICT_KEY.
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

// Mixed into the verdict so that neither evaluation alone produces the pass token,
// and therefore not a valid pass_token.
#define ABR_DRV_VERDICT_KEY 0xC3A5965Au

// Where a call ended, in execution order; for diagnostics only. The values are
// fixed because test logs and other tools record the number.
typedef enum {
    ABR_DRV_STAGE_ARGS = 0,
    ABR_DRV_STAGE_IDENTITY = 1,
    ABR_DRV_STAGE_ZEROIZE = 2,
    ABR_DRV_STAGE_LOAD = 3,
    ABR_DRV_STAGE_ARM = 4,
    ABR_DRV_STAGE_START = 5,
    ABR_DRV_STAGE_PRELOAD = 6,
    ABR_DRV_STAGE_STREAM_WAIT = 7,
    ABR_DRV_STAGE_STREAM = 8,
    ABR_DRV_STAGE_COMPLETE = 9,
    ABR_DRV_STAGE_READBACK = 10,
    ABR_DRV_STAGE_VERDICT = 11,
    ABR_DRV_STAGE_DONE = 12
} abr_drv_stage_e;

typedef struct {
    uint32_t bytes_written; // message bytes written to MSG
    uint32_t early_valid;   // 1 if VALID rose before MSG_STREAM_READY
    uint32_t res_inverse;   // 1 if VERIFY_RES equalled ~c~ at completion
    uint32_t res_nonzero;   // 1 if VERIFY_RES was not all-zero at completion
    uint32_t done_count;    // command-done events the accelerator counted
    uint32_t status;        // the STATUS read that ended a wait or failed a check
    uint32_t stage;         // abr_drv_stage_e
} abr_drv_diag_t;

// Check the ML-DSA name and version registers. ABR_DRV_OK or ABR_DRV_ERR_IDENTITY.
int abr_drv_check_identity(void);

// Zeroize the accelerator and wait for STATUS to read READY alone.
int abr_drv_zeroize(void);

// Verify signature over message_len bytes of message under public_key.
//
// The signature is valid only when *verdict equals pass_token; every other outcome
// writes ~pass_token. ABR_DRV_OK alone is not evidence of a valid signature: a single
// fault can produce it, so compare *verdict, the hardened result. diag may be NULL.
int abr_mldsa87_verify(const uint8_t *public_key, const uint8_t *signature, const uint8_t *message,
                       uint32_t message_len, uint32_t pass_token, uint32_t *verdict,
                       abr_drv_diag_t *diag);

#endif // ABR_DRIVER_H
