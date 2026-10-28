/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Scriptable stand-in for the Adams Bridge register file, for driver host tests.
//
// By default it behaves like the RTL on a streamed ML-DSA verify: zeroize returns
// STATUS to READY and MSG_STROBE to 0, VERIFY preloads VERIFY_RES with ~c~,
// MSG_STREAM_READY rises, the first strobe other than 0xF ends the stream, then VALID
// rises with one command-done event. VERIFY_RES is c~ only if the stream was exactly
// the signed message, as a real signature over it would give. Each field below bends
// one step; the record fields say what the driver did.

#ifndef FAKE_ABR_H
#define FAKE_ABR_H

#include <stdint.h>

#define FAKE_ABR_MAX_STREAM 70000u

typedef enum {
    FAKE_RES_MATCH,    // VERIFY_RES = c~ at VALID if the stream was signed, else c~ changed
    FAKE_RES_MISMATCH, // VERIFY_RES = c~ with one word changed
    FAKE_RES_INVERSE,  // VERIFY_RES keeps the ~c~ preload
    FAKE_RES_ZERO      // VERIFY_RES = 0
} fake_res_e;

typedef struct {
    // --- script --------------------------------------------------------------
    int zeroize_polls;          // STATUS polls after ZEROIZE before READY
    int zeroize_never_ready;    // STATUS never returns to READY after ZEROIZE
    uint32_t zeroize_status;    // if non-zero, STATUS after zeroize reads this while
                                // the registers accept writes as if READY
    int trailing_zeroize_fails; // the second and later zeroizes never complete
    int stream_ready_polls;     // STATUS polls after the command before MSG_STREAM_READY
    int never_stream_ready;     // neither MSG_STREAM_READY nor VALID ever rises
    int early_valid;            // VALID rises instead of MSG_STREAM_READY
    int complete_polls;         // STATUS polls after the last strobe before VALID
    int never_valid;            // VALID never rises after the stream
    int error_in_stream_wait;   // STATUS.ERROR while waiting for MSG_STREAM_READY
    int error_in_complete_wait; // STATUS.ERROR while waiting for VALID
    int no_preload;             // VERIFY_RES stays 0 when VERIFY is accepted
    fake_res_e result;
    int mismatch_word;        // the c~ word FAKE_RES_MISMATCH changes
    int second_res_differs;   // a second pass over VERIFY_RES reads different data
    int pk_readback_corrupt;  // PUBKEY reads back with one word changed
    int sig_readback_corrupt; // SIGNATURE c~ reads back with one word changed
    int done_events;          // command-done events at VALID (default 1)
    int done_sts_cleared;     // notif_cmd_done_sts reads 0 at VALID
    int error_event;          // an internal-error event accompanies VALID
    int error_sts_only;       // ... setting only the error status
    int error_count_only;     // ... raising only the error counter
    int done_sts_sticks;      // writes clearing notif_cmd_done_sts are ignored
    int done_count_sticks;    // writes to the done counter are ignored
    int identity_bad;         // MLDSA_VERSION reads a different value

    int err_sts_sticks;        // writes clearing error_internal_sts are ignored
    int err_count_sticks;      // writes to the error counter are ignored
    const uint8_t *signed_msg; // the message the signature is over
    uint32_t signed_len;       // and its length
    int signed_prefixes;       // every prefix of signed_msg is signed too
    uint32_t drop_write;       // if non-zero, the drop_write-th register write is lost
    uint32_t corrupt_strobe;   // if non-zero, the corrupt_strobe-th MSG_STROBE write ...
    uint32_t corrupt_value;    // ... stores this value instead

    // --- record --------------------------------------------------------------
    int zeroize_count;
    int verify_commands;
    int bad_width_accesses;
    int out_of_window_accesses;
    int msg_outside_stream;
    int strobe_outside_stream;
    int fence_count;
    uint32_t write_count;
    uint32_t strobe_writes;
    uint32_t stream_len;
    uint8_t stream[FAKE_ABR_MAX_STREAM];
    uint32_t strobes[FAKE_ABR_MAX_STREAM / 4u + 2u];
    uint32_t strobe_count;
    uint32_t ctx_config;
    uint32_t pubkey[648];
    uint32_t signature[1157];
    uint32_t verified_pubkey[648]; // PUBKEY and c~ when VALID last rose
    uint32_t verified_ctilde[16];
} fake_abr_t;

extern fake_abr_t g_fake;

void fake_abr_reset(void);

#endif // FAKE_ABR_H
