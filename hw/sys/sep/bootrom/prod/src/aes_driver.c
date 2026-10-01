/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// AES-128-CBC decryption driver for OROM.
//
// Drives the OpenTitan AES IP at SEP_TOP_AES_BASE_ADDR (0x10910000).
// Register interface and flow ported from:
//   fw/sep/tests/sep_aes_basic_smoke_test/sep_aes_basic_smoke_test.c
//
// AES-128-CBC decryption sequence:
//   1. Release AES from SW reset
//   2. Configure: DEC mode, CBC, AES-128, automatic operation
//   3. Write key (KEY_SHARE0, KEY_SHARE1=0)
//   4. Write IV
//   5. For each 16-byte block: write DATA_IN, wait OUTPUT_VALID, read DATA_OUT
//   6. Cleanup: clear key/IV/data

#include "aes_driver.h"

#include <stdbool.h>
#include <stdint.h>

#include "rom_mmio.h"
#include "sep.h"
#include <stddef.h>

#include "errors.h"

// AES operation modes.
#define AES_OP_ENCRYPT 0x1u
#define AES_OP_DECRYPT 0x2u
#define AES_MODE_ECB 0x01u
#define AES_MODE_CBC 0x02u
// KEY_LEN is a 3-bit ONE-HOT field, not an encoded width (aes.rdl:127). Invalid
// values -- multiple bits, zero, or 192 on a build without it -- are mapped to
// AES_256 by the hardware, so these are the only three legal writes.
#define AES_KEYLEN_128 0x1u
#define AES_KEYLEN_192 0x2u
#define AES_KEYLEN_256 0x4u

// Timeout for AES status polling.
#define AES_TIMEOUT 1000000

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

static int wait_idle(void) {
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        aes__STATUS_t s;
        s.w = mmio_read32(SEP_TOP_AES_STATUS_BASE_ADDR);
        if (s.f.IDLE) return 0;
    }
    // Report the register rather than just the timeout. The two ways this fails
    // look identical from the outside but have opposite fixes: STATUS == 0 means
    // nothing is answering (block still in reset, or its AXI port isolated),
    // while a non-zero STATUS with IDLE clear means the core is alive and stuck
    // busy -- which is what an AES waiting on an EDN reseed that never arrives
    // looks like. Both were hit bringing this path up in simulation, and without
    // this value they are a full debug cycle apart.
    simputs("AES_IDLE_TIMEOUT=");
    simputhex32(mmio_read32(SEP_TOP_AES_STATUS_BASE_ADDR));
    simputs("\n");
    return -1;
}

// A shadowed CTRL update that does not take raises ALERT_RECOV_CTRL_UPDATE_ERR
// and leaves the engine on the PREVIOUS configuration while IDLE / INPUT_READY /
// OUTPUT_VALID all look normal, so those three cannot tell "configured as asked"
// from "rejected, still on stale settings". ALERT_FATAL_FAULT is unrecoverable.
static int check_no_alert(void) {
    aes__STATUS_t s;
    s.w = mmio_read32(SEP_TOP_AES_STATUS_BASE_ADDR);
    if (s.f.ALERT_RECOV_CTRL_UPDATE_ERR || s.f.ALERT_FATAL_FAULT) {
        simputshex32("AES_ALERT_STATUS=", s.w);
        return -1;
    }
    return 0;
}

static int wait_input_ready(void) {
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        aes__STATUS_t s;
        s.w = mmio_read32(SEP_TOP_AES_STATUS_BASE_ADDR);
        if (s.f.INPUT_READY) return 0;
    }
    return -1;
}

static int wait_output_valid(void) {
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        aes__STATUS_t s;
        s.w = mmio_read32(SEP_TOP_AES_STATUS_BASE_ADDR);
        if (s.f.OUTPUT_VALID) return 0;
    }
    return -1;
}

// Write CTRL_SHADOWED (must be written twice for shadowed register).
static void write_ctrl(uint32_t val) {
    mmio_write32(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, val);
    mmio_write32(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, val);
}

// Load a key of key_bytes (16 or 32) into KEY_SHARE0, zero-filling the rest of
// the 8-word register file. The register file is 8 words per share (aes.rdl:36),
// i.e. it always holds a full 256-bit key; a shorter key occupies the low words
// and KEY_LEN tells the engine how much of it to use.
static void write_key(const uint8_t *key, uint32_t key_bytes) {
    const uint32_t words = key_bytes / 4u;
    for (uint32_t i = 0; i < words; ++i) {
        uint32_t w = (uint32_t)key[i * 4] | ((uint32_t)key[i * 4 + 1] << 8) |
                     ((uint32_t)key[i * 4 + 2] << 16) | ((uint32_t)key[i * 4 + 3] << 24);
        mmio_write32(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(0) + (i * 4u), w);
    }
    for (uint32_t i = words; i < 8u; ++i) {
        mmio_write32(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(0) + (i * 4u), 0u);
    }

    // KEY_SHARE1: all zeros (no masking).
    for (uint32_t i = 0; i < 8u; ++i) {
        mmio_write32(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(0) + (i * 4u), 0u);
    }
}

static void write_iv(const uint8_t *iv) {
    for (int i = 0; i < 4; ++i) {
        uint32_t w = (uint32_t)iv[i * 4] | ((uint32_t)iv[i * 4 + 1] << 8) |
                     ((uint32_t)iv[i * 4 + 2] << 16) | ((uint32_t)iv[i * 4 + 3] << 24);
        mmio_write32(SEP_TOP_AES_IV_BASE_ADDR(0) + (uint32_t)(i * 4), w);
    }
}

static void write_data_in(const uint8_t *in) {
    for (int i = 0; i < 4; ++i) {
        uint32_t w = (uint32_t)in[i * 4] | ((uint32_t)in[i * 4 + 1] << 8) |
                     ((uint32_t)in[i * 4 + 2] << 16) | ((uint32_t)in[i * 4 + 3] << 24);
        mmio_write32(SEP_TOP_AES_DATA_IN_BASE_ADDR(0) + (uint32_t)(i * 4), w);
    }
}

static void read_data_out(uint8_t *out) {
    for (int i = 0; i < 4; ++i) {
        uint32_t w = mmio_read32(SEP_TOP_AES_DATA_OUT_BASE_ADDR(0) + (uint32_t)(i * 4));
        out[i * 4] = (uint8_t)(w);
        out[i * 4 + 1] = (uint8_t)(w >> 8);
        out[i * 4 + 2] = (uint8_t)(w >> 16);
        out[i * 4 + 3] = (uint8_t)(w >> 24);
    }
}

static void aes_cleanup(void) {
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = AES_OP_DECRYPT;
    ctrl.f.MODE = AES_MODE_ECB;
    ctrl.f.KEY_LEN = AES_KEYLEN_128;
    ctrl.f.MANUAL_OPERATION = 1;
    write_ctrl(ctrl.w);

    aes__TRIGGER_t trig = {.w = 0};
    trig.f.KEY_IV_DATA_IN_CLEAR = 1;
    trig.f.DATA_OUT_CLEAR = 1;
    mmio_write32(SEP_TOP_AES_TRIGGER_BASE_ADDR, trig.w);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int aes_init(void) {
    // Entropy is a PREREQUISITE of this block, not something it brings up: the
    // masking PRNG reseeds off EDN before the core reports STATUS.IDLE. The
    // caller establishes it (see oca_platform.c).
    // Release AES from SW reset.
    uint32_t rst = mmio_read32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);
    rst |= SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm;
    mmio_write32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, rst);
    __asm__ volatile("fence" ::: "memory");

    if (!(mmio_read32(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
          SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm)) {
        simputs("AES_RST_FAIL\n");
        return -1;
    }

    // Coming out of reset the AES seeds its masking PRNG from EDN and reports
    // BUSY until that completes, and while busy it ignores CTRL_SHADOWED writes
    // (aes_ctrl_reg_shadowed.sv). Waiting here is required by that contract.
    // Defensive only: no observed failure here was caused by its absence.
    if (wait_idle() != 0) {
        simputs("AES_INIT_BUSY\n");
        return -1;
    }

    return 0;
}

int aes_cbc_decrypt(uint8_t *data, uint32_t len, const uint8_t *key, uint32_t key_bytes,
                    const uint8_t *iv) {
    if (len == 0u || (len & 0xFu) != 0u) {
        return -1; // Must be non-zero and multiple of 16.
    }

    uint32_t key_len_field;
    switch (key_bytes) {
    case 16u:
        key_len_field = AES_KEYLEN_128;
        break;
    case 32u:
        key_len_field = AES_KEYLEN_256;
        break;
    default:
        // Not defaulted to AES-256 the way the hardware would: a caller passing
        // a width this driver does not know is a bug, and silently using a
        // different key length would decrypt to garbage rather than fail.
        simputs("AES_BAD_KEYLEN\n");
        return -1;
    }

    // Configure: DEC, CBC, automatic.
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = AES_OP_DECRYPT;
    ctrl.f.MODE = AES_MODE_CBC;
    ctrl.f.KEY_LEN = key_len_field;
    ctrl.f.SIDELOAD = 0;
    ctrl.f.MANUAL_OPERATION = 0;

    // CTRL_SHADOWED only takes effect while the unit is idle; see aes_init().
    if (wait_idle() != 0) goto fail;
    write_ctrl(ctrl.w);

    // Confirm the shadowed write actually landed before any key or data follows
    // it; a rejected update would otherwise decrypt under the previous config.
    if (check_no_alert() != 0) {
        simputs("AES_CTRL_REJECTED\n");
        goto fail;
    }

    if (wait_idle() != 0) goto fail;

    write_key(key, key_bytes);

    // A KEY write starts a PRNG reseed, and a KEY or IV write while busy is
    // ignored like a CTRL write, so the IV write is separated by an idle wait.
    if (wait_idle() != 0) goto fail;

    write_iv(iv);

    if (wait_idle() != 0) goto fail;

    // Process each 16-byte block.
    uint32_t blocks = len >> 4;
    for (uint32_t b = 0; b < blocks; ++b) {
        if (wait_input_ready() != 0) goto fail;

        uint8_t *blk = data + b * 16u;
        write_data_in(blk);

        if (wait_output_valid() != 0) goto fail;

        read_data_out(blk); // Decrypt in-place.
    }

    // A fault raised mid-stream would otherwise be reported as a clean decrypt.
    if (check_no_alert() != 0) {
        simputs("AES_ALERT_AFTER_DEC\n");
        goto fail;
    }

    aes_cleanup();
    return 0;

fail:
    simputs("AES_DEC_FAIL\n");
    aes_cleanup();
    return -1;
}

// Strip PKCS#7 padding from a decrypted CBC buffer, returning the recovered
// length via out_len.
//
// Constant time in the padding VALUE, which is the part an attacker controls by
// tampering with the last ciphertext block: the length check and every pad byte
// are folded into one accumulator rather than exiting on the first bad byte. It
// is not constant time in the buffer length, which is public.
//
// This is deliberately not a padding-oracle-free construction on its own -- the
// only defence against that is what the caller already did: the OCA library
// verifies payload_hash over the ciphertext BEFORE decrypting, so an attacker
// cannot submit chosen ciphertexts to probe this at all.
int aes_pkcs7_strip(const uint8_t *data, uint32_t len, uint32_t *out_len) {
    if (data == NULL || out_len == NULL || len == 0u || (len & 0xFu) != 0u) {
        return -1;
    }

    const uint32_t pad = (uint32_t)data[len - 1u];

    // 1..16 and no larger than the buffer. Folded, not branched.
    uint32_t bad = 0u;
    bad |= (pad == 0u) ? 1u : 0u;
    bad |= (pad > 16u) ? 1u : 0u;
    bad |= (pad > len) ? 1u : 0u;

    // Every padding byte must equal the count. Walk a fixed 16 bytes so the
    // number of iterations does not reveal the claimed pad length.
    for (uint32_t i = 0; i < 16u; ++i) {
        // Bytes beyond the claimed padding are not checked, but the mask is
        // computed rather than branched on.
        const uint32_t in_pad = (i < pad) ? 1u : 0u;
        const uint8_t b = data[len - 1u - i];
        bad |= in_pad & ((b ^ (uint8_t)pad) != 0u ? 1u : 0u);
    }

    if (bad != 0u) {
        simputs("AES_PAD_BAD\n");
        return -1;
    }
    *out_len = len - pad;
    return 0;
}
