// HMAC SHA-256 hardware driver for OROM.
//
// Drives the OpenTitan HMAC IP in SHA-256-only mode or HMAC mode.
// SHA-256: configure(hmac_en=0) → hash_start → feed FIFO → hash_process → read digest.
// HMAC:    write KEY → configure(hmac_en=1) → hash_start → feed FIFO → hash_process → read digest.
//
// Reference: fw/sep/tests/hmac_test/hmac_test.c (validated against NIST vectors).

#include "hmac_sha256.h"

#include <stdbool.h>

#include "rom_mmio.h"
#include "och_sep_top_reg.h"

// Hardware timeout: generous limit for SHA-256 block processing.
// Each 64-byte block takes ~80 cycles; 1M iterations covers any realistic message.
#define HMAC_TIMEOUT 1000000

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Wait for hmac_done interrupt or hmac_idle status.
// Returns 0 on success, -1 on timeout.
static int wait_for_completion(void) {
    for (int i = 0; i < HMAC_TIMEOUT; ++i) {
        HMAC_INTR_STATE_reg_u intr;
        intr.val = mmio_read32(HMAC_INTR_STATE_REG_ADDR);
        if (intr.f.hmac_done) {
            // Clear hmac_done (write-1-to-clear).
            HMAC_INTR_STATE_reg_u clear = {.f.hmac_done = 1};
            mmio_write32(HMAC_INTR_STATE_REG_ADDR, clear.val);
            return 0;
        }

        HMAC_STATUS_reg_u sts;
        sts.val = mmio_read32(HMAC_STATUS_REG_ADDR);
        if (sts.f.hmac_idle) {
            return 0;
        }
    }
    return -1;
}

// Feed data into the MSG_FIFO.
// Uses 32-bit word writes for aligned bulk, byte writes for head/tail.
static void fifo_feed(const uint8_t *data, uint32_t len) {
    uint32_t i = 0;

    // Byte-by-byte until 4-byte aligned (or done).
    while (i < len && ((uintptr_t)(data + i) & 3u)) {
        // Poll fifo_full before each write.
        HMAC_STATUS_reg_u s;
        do {
            s.val = mmio_read32(HMAC_STATUS_REG_ADDR);
        } while (s.f.fifo_full);
        mmio_write8(HMAC_MSG_FIFO_MEM_BASE_ADDR, data[i]);
        ++i;
    }

    // Word-aligned bulk transfer.
    while (i + 4u <= len) {
        HMAC_STATUS_reg_u s;
        do {
            s.val = mmio_read32(HMAC_STATUS_REG_ADDR);
        } while (s.f.fifo_full);

        uint32_t word;
        // Memcpy-equivalent for strict-aliasing safety.
        const uint8_t *p = data + i;
        word = (uint32_t)p[0];
        word |= (uint32_t)p[1] << 8;
        word |= (uint32_t)p[2] << 16;
        word |= (uint32_t)p[3] << 24;
        mmio_write32(HMAC_MSG_FIFO_MEM_BASE_ADDR, word);
        i += 4u;
    }

    // Remaining tail bytes.
    while (i < len) {
        HMAC_STATUS_reg_u s;
        do {
            s.val = mmio_read32(HMAC_STATUS_REG_ADDR);
        } while (s.f.fifo_full);
        mmio_write8(HMAC_MSG_FIFO_MEM_BASE_ADDR, data[i]);
        ++i;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int sha256(const uint8_t *data, uint32_t len, uint8_t *digest) {
    // 1. Clear any pending interrupt state.
    mmio_write32(HMAC_INTR_STATE_REG_ADDR, 0x7u); // clear all 3 bits

    // 2. Configure: SHA-256, no HMAC, no endian swap, no digest swap.
    HMAC_CFG_reg_u cfg = {.val = 0};
    cfg.f.hmac_en = 0;     // SHA-only (no HMAC key)
    cfg.f.sha_en = 1;      // Enable SHA engine
    cfg.f.endian_swap = 0; // Little-endian input
    cfg.f.digest_swap = 0; // No digest byte swap
    cfg.f.digest_size = 1; // SHA2-256
    mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);

    // 3. Start a new hash operation.
    HMAC_CMD_reg_u cmd_start = {.f.hash_start = 1};
    mmio_write32(HMAC_CMD_REG_ADDR, cmd_start.val);

    // 4. Feed message data into FIFO.
    fifo_feed(data, len);

    // 5. Signal end of message → hardware computes final digest.
    HMAC_CMD_reg_u cmd_process = {.f.hash_process = 1};
    mmio_write32(HMAC_CMD_REG_ADDR, cmd_process.val);

    // 6. Wait for completion.
    if (wait_for_completion() != 0) {
        // Timeout — disable and wipe.
        cfg.f.sha_en = 0;
        mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);
        mmio_write32(HMAC_WIPE_SECRET_REG_ADDR, 0xFFFFFFFFu);
        return -1;
    }

    // 7. Read 256-bit digest (8 × 32-bit words).
    //    Hardware digest registers hold big-endian words (MSB at bits[31:24]).
    //    Extract bytes MSB-first for standard SHA-256 byte order.
    for (int i = 0; i < 8; ++i) {
        uint32_t raw = mmio_read32(HMAC_DIGEST_0__REG_ADDR + (uint32_t)(i * 4));
        digest[i * 4 + 0] = (uint8_t)(raw >> 24);
        digest[i * 4 + 1] = (uint8_t)(raw >> 16);
        digest[i * 4 + 2] = (uint8_t)(raw >> 8);
        digest[i * 4 + 3] = (uint8_t)(raw);
    }

    // 8. Cleanup: disable SHA engine and wipe internal state.
    cfg.f.sha_en = 0;
    mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);
    mmio_write32(HMAC_WIPE_SECRET_REG_ADDR, 0xFFFFFFFFu);

    return 0;
}

int hmac_sha256(const uint8_t *key, uint32_t key_len, const uint8_t *data, uint32_t data_len,
                uint8_t *digest) {
    if (key_len > 32u) return -1; // IP supports 256-bit key max.

    // 1. Clear any pending interrupt state.
    mmio_write32(HMAC_INTR_STATE_REG_ADDR, 0x7u);

    // 2. Write HMAC key to KEY_0..KEY_7 (before enabling HMAC).
    //    Key bytes are written in little-endian word order.
    //    Unused bytes are zero-padded.
    for (int w = 0; w < 8; ++w) {
        uint32_t word = 0;
        for (int b = 0; b < 4; ++b) {
            uint32_t idx = (uint32_t)(w * 4 + b);
            if (idx < key_len) {
                word |= (uint32_t)key[idx] << (b * 8);
            }
        }
        mmio_write32(HMAC_KEY_0__REG_ADDR + (uint32_t)(w * 4), word);
    }

    // 3. Configure: HMAC + SHA-256 mode.
    HMAC_CFG_reg_u cfg = {.val = 0};
    cfg.f.hmac_en = 1;     // HMAC mode (uses KEY registers)
    cfg.f.sha_en = 1;      // Enable SHA engine
    cfg.f.endian_swap = 0; // Little-endian input
    cfg.f.digest_swap = 0; // No digest byte swap
    cfg.f.digest_size = 1; // SHA2-256
    mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);

    // 4. Start HMAC operation.
    HMAC_CMD_reg_u cmd_start = {.f.hash_start = 1};
    mmio_write32(HMAC_CMD_REG_ADDR, cmd_start.val);

    // 5. Feed message data.
    fifo_feed(data, data_len);

    // 6. Signal end of message.
    HMAC_CMD_reg_u cmd_process = {.f.hash_process = 1};
    mmio_write32(HMAC_CMD_REG_ADDR, cmd_process.val);

    // 7. Wait for completion.
    if (wait_for_completion() != 0) {
        cfg.f.hmac_en = 0;
        cfg.f.sha_en = 0;
        mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);
        mmio_write32(HMAC_WIPE_SECRET_REG_ADDR, 0xFFFFFFFFu);
        return -1;
    }

    // 8. Read 256-bit HMAC digest.
    for (int i = 0; i < 8; ++i) {
        uint32_t raw = mmio_read32(HMAC_DIGEST_0__REG_ADDR + (uint32_t)(i * 4));
        digest[i * 4 + 0] = (uint8_t)(raw >> 24);
        digest[i * 4 + 1] = (uint8_t)(raw >> 16);
        digest[i * 4 + 2] = (uint8_t)(raw >> 8);
        digest[i * 4 + 3] = (uint8_t)(raw);
    }

    // 9. Cleanup.
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 0;
    mmio_write32(HMAC_CFG_REG_ADDR, cfg.val);
    mmio_write32(HMAC_WIPE_SECRET_REG_ADDR, 0xFFFFFFFFu);

    return 0;
}
