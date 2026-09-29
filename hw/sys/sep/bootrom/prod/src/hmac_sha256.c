/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// HMAC SHA-256 hardware driver for OROM.
//
// Drives the OpenTitan HMAC IP in SHA-256-only mode or HMAC mode.
// SHA-256: configure(hmac_en=0) → hash_start → feed FIFO → hash_process → read digest.
// HMAC:    write KEY → configure(hmac_en=1) → hash_start → feed FIFO → hash_process → read digest.
//
// The word<->byte conventions here are pinned by hw/sys/sep/dv/fw/tests/
// hmac_hmac_mode_sha256_test, which reproduces RFC 4231 test case 2 on this IP:
// message little-endian with endian_swap=0, digest and KEY big-endian per word.

#include "hmac_sha256.h"

#include <stdbool.h>

#include "rom_mmio.h"
#include "rom_virt_console.h"
#include "sep.h"

// Hardware timeout: generous limit for SHA-256 block processing.
// Each 64-byte block takes ~80 cycles; 1M iterations covers any realistic message.
#define HMAC_TIMEOUT 1000000

// CFG.digest_size / CFG.key_length are enumerated, not numeric: 0 is not "don't
// care", it decodes to the None member. hmac.sv gates hash_start AND hash_process
// on ~invalid_config, and invalid_config is asserted for an unset digest_size, or
// for an unset key_length while hmac_en=1 -- so leaving either at 0 makes the
// operation silently never run.
#define HMAC_DIGEST_SIZE_SHA2_256 0x1u
// Message-FIFO capacity in 32-bit entries. From the IP itself:
// vendor/lowRISC/opentitan/upstream/hw/ip/hmac/rtl/hmac.sv
//   localparam int MsgFifoDepth = 32;  ... prim_fifo_sync #(.Depth(MsgFifoDepth))
// Nothing in this tree overrides it. STATUS.fifo_depth counts the same entries.
#define HMAC_MSG_FIFO_WORDS 32u

#define HMAC_KEY_LENGTH_128 0x1u
#define HMAC_KEY_LENGTH_256 0x2u

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Wait for hmac_done interrupt or hmac_idle status.
// Returns 0 on success, -1 on timeout.
static int wait_for_completion(void) {
    for (int i = 0; i < HMAC_TIMEOUT; ++i) {
        hmac__INTR_STATE_t intr;
        intr.w = mmio_read32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
        if (intr.f.hmac_done) {
            // Clear hmac_done (write-1-to-clear).
            hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
            mmio_write32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
            return 0;
        }

        hmac__STATUS_t sts;
        sts.w = mmio_read32(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        if (sts.f.hmac_idle) {
            return 0;
        }
    }
    return -1;
}

// Check whether the IP rejected the operation.
//
// This cannot be folded into wait_for_completion(). A rejected operation never
// starts, so STATUS.hmac_idle stays asserted and the wait returns success
// immediately -- the caller then reads whatever the DIGEST registers happen to
// hold and treats it as a real digest. The only signal that separates "finished"
// from "never ran" is INTR_STATE.hmac_err, so it has to be read on its own.
// ERR_CODE names the cause (SwInvalidConfig, SwHashStartWhenShaDisabled, ...).
static int check_no_error(void) {
    hmac__INTR_STATE_t intr;
    intr.w = mmio_read32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!intr.f.hmac_err) return 0;

    simputshex32("HMAC_ERR_CODE=", mmio_read32(SEP_TOP_HMAC_ERR_CODE_BASE_ADDR));
    hmac__INTR_STATE_t clear = {.f.hmac_err = 1};
    mmio_write32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    return -1;
}

// Feed data into the MSG_FIFO.
// Uses 32-bit word writes for aligned bulk, byte writes for head/tail.
static void fifo_feed(const uint8_t *data, uint32_t len) {
    uint32_t i = 0;

    // Byte-by-byte until 4-byte aligned (or done).
    while (i < len && ((uintptr_t)(data + i) & 3u)) {
        // Poll fifo_full before each write.
        hmac__STATUS_t s;
        do {
            s.w = mmio_read32(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        } while (s.f.fifo_full);
        mmio_write8(SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR, data[i]);
        ++i;
    }

    // Word-aligned bulk transfer, one STATUS read per BATCH of writes rather
    // than per write.
    //
    // STATUS.fifo_depth is the FIFO's current occupancy in 32-bit entries,
    // driven straight from u_msg_fifo's depth_o, and the FIFO is 32 entries
    // deep (hmac.sv: localparam int MsgFifoDepth = 32, passed as .Depth).
    // So one read yields a write credit of HMAC_MSG_FIFO_WORDS - fifo_depth.
    //
    // Why the credit is safe: the engine drains the FIFO concurrently while we
    // write, so the free space at the moment of any later write is >= what the
    // read reported. The credit is therefore a conservative lower bound and can
    // never overestimate the room available -- which is what makes it correct
    // to skip the intermediate polls rather than merely faster.
    //
    // This matters because the boot measurement hashes the whole ROM region
    // (~32 KiB): at one status read per word that was ~8k extra MMIO reads,
    // roughly half the bus traffic of the hash, and MMIO round-trips dominate
    // this loop in simulation.
    uint32_t credit = 0u;
    while (i + 4u <= len) {
        if (credit == 0u) {
            hmac__STATUS_t s;
            do {
                s.w = mmio_read32(SEP_TOP_HMAC_STATUS_BASE_ADDR);
                // fifo_depth is a 6-bit field, so it can encode values above
                // the real capacity. Clamp rather than let the unsigned
                // subtraction wrap into a huge credit.
                credit = (s.f.fifo_depth >= HMAC_MSG_FIFO_WORDS)
                             ? 0u
                             : (HMAC_MSG_FIFO_WORDS - s.f.fifo_depth);
            } while (credit == 0u);
        }

        uint32_t word;
        // Memcpy-equivalent for strict-aliasing safety.
        const uint8_t *p = data + i;
        word = (uint32_t)p[0];
        word |= (uint32_t)p[1] << 8;
        word |= (uint32_t)p[2] << 16;
        word |= (uint32_t)p[3] << 24;
        mmio_write32(SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR, word);
        i += 4u;
        --credit;
    }

    // Remaining tail bytes.
    while (i < len) {
        hmac__STATUS_t s;
        do {
            s.w = mmio_read32(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        } while (s.f.fifo_full);
        mmio_write8(SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR, data[i]);
        ++i;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int sha256(const uint8_t *data, uint32_t len, uint8_t *digest) {
    // 1. Clear any pending interrupt state.
    mmio_write32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, 0x7u); // clear all 3 bits

    // 2. Configure: SHA-256, no HMAC, no endian swap, no digest swap.
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;     // SHA-only (no HMAC key)
    cfg.f.sha_en = 1;      // Enable SHA engine
    cfg.f.endian_swap = 0; // Little-endian input
    cfg.f.digest_swap = 0; // No digest byte swap
    cfg.f.digest_size = HMAC_DIGEST_SIZE_SHA2_256;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    // 3. Start a new hash operation.
    hmac__CMD_t cmd_start = {.f.hash_start = 1};
    mmio_write32(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_start.w);

    if (check_no_error() != 0) {
        simputs("SHA_START_REJECTED\n");
        goto fail;
    }

    // 4. Feed message data into FIFO.
    fifo_feed(data, len);

    // 5. Signal end of message → hardware computes final digest.
    hmac__CMD_t cmd_process = {.f.hash_process = 1};
    mmio_write32(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_process.w);

    // 6. Wait for completion, then confirm nothing was rejected.
    if (wait_for_completion() != 0) goto fail;
    if (check_no_error() != 0) {
        simputs("SHA_OP_REJECTED\n");
        goto fail;
    }

    // 7. Read 256-bit digest (8 × 32-bit words).
    //    Hardware digest registers hold big-endian words (MSB at bits[31:24]).
    //    Extract bytes MSB-first for standard SHA-256 byte order.
    for (int i = 0; i < 8; ++i) {
        uint32_t raw = mmio_read32(SEP_TOP_HMAC_DIGEST_BASE_ADDR(0) + (uint32_t)(i * 4));
        digest[i * 4 + 0] = (uint8_t)(raw >> 24);
        digest[i * 4 + 1] = (uint8_t)(raw >> 16);
        digest[i * 4 + 2] = (uint8_t)(raw >> 8);
        digest[i * 4 + 3] = (uint8_t)(raw);
    }

    // 8. Cleanup: disable SHA engine and wipe internal state.
    cfg.f.sha_en = 0;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    mmio_write32(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);

    return 0;

fail:
    cfg.f.sha_en = 0;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    mmio_write32(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    return -1;
}

int hmac_sha256(const uint8_t *key, uint32_t key_len, const uint8_t *data, uint32_t data_len,
                uint8_t *digest) {
    if (key_len > 32u) return -1; // IP supports 256-bit key max.

    // 1. Clear any pending interrupt state.
    mmio_write32(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, 0x7u);

    // 2. Write HMAC key to KEY_0..KEY_7 (before enabling HMAC).
    //    Big-endian per word: key[0] is KEY_0[31:24]. The IP applies
    //    conv_endian32(key, key_swap) and key_swap is left at its reset value 0,
    //    i.e. no swap, so the register word is consumed as written. Unused bytes
    //    are zero-padded, which is HMAC-equivalent to a shorter key: RFC 2104
    //    zero-extends any key below the 64-byte block size anyway.
    for (int w = 0; w < 8; ++w) {
        uint32_t word = 0;
        for (int b = 0; b < 4; ++b) {
            uint32_t idx = (uint32_t)(w * 4 + b);
            if (idx < key_len) {
                word |= (uint32_t)key[idx] << (24 - b * 8);
            }
        }
        mmio_write32(SEP_TOP_HMAC_KEY_BASE_ADDR(0) + (uint32_t)(w * 4), word);
    }

    // 3. Configure: HMAC + SHA-256 mode.
    //
    // key_length is REQUIRED in HMAC mode and is a 6-bit one-hot field, not a
    // byte count (hmac.rdl:138-153). Its reset value is Key_None (0x20), and the
    // IP blocks the start and raises hmac_err when HMAC is triggered with
    // Key_None, so an unset field fails every HMAC operation and reads back
    // 0xFFFFFFFF digests. Only the keyed path configures it; sha256() does not.
    uint32_t key_length_field;
    if (key_len <= 16u) {
        key_length_field = HMAC_KEY_LENGTH_128;
    } else {
        key_length_field = HMAC_KEY_LENGTH_256;
    }

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 1;     // HMAC mode (uses KEY registers)
    cfg.f.sha_en = 1;      // Enable SHA engine
    cfg.f.endian_swap = 0; // Little-endian input
    cfg.f.digest_swap = 0; // No digest byte swap
    cfg.f.digest_size = HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.key_length = key_length_field;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    // 4. Start HMAC operation.
    hmac__CMD_t cmd_start = {.f.hash_start = 1};
    mmio_write32(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_start.w);

    // A bad CFG is reported at hash_start and blocks the operation outright, so
    // this must be checked before feeding the message.
    if (check_no_error() != 0) {
        simputs("HMAC_START_REJECTED\n");
        goto fail;
    }

    // 5. Feed message data.
    fifo_feed(data, data_len);

    // 6. Signal end of message.
    hmac__CMD_t cmd_process = {.f.hash_process = 1};
    mmio_write32(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_process.w);

    // 7. Wait for completion, then confirm the IP did not reject anything along
    //    the way (a rejected message push also lands here).
    if (wait_for_completion() != 0) goto fail;
    if (check_no_error() != 0) {
        simputs("HMAC_OP_REJECTED\n");
        goto fail;
    }

    // 8. Read 256-bit HMAC digest.
    for (int i = 0; i < 8; ++i) {
        uint32_t raw = mmio_read32(SEP_TOP_HMAC_DIGEST_BASE_ADDR(0) + (uint32_t)(i * 4));
        digest[i * 4 + 0] = (uint8_t)(raw >> 24);
        digest[i * 4 + 1] = (uint8_t)(raw >> 16);
        digest[i * 4 + 2] = (uint8_t)(raw >> 8);
        digest[i * 4 + 3] = (uint8_t)(raw);
    }

    // 9. Cleanup.
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 0;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    mmio_write32(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);

    return 0;

fail:
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 0;
    mmio_write32(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    mmio_write32(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    return -1;
}
