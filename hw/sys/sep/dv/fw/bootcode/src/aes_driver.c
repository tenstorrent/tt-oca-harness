// AES-128-CBC decryption driver for OROM.
//
// Drives the OpenTitan AES IP at AES_REG_MAP_BASE_ADDR (0x10910000).
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
#include "och_sep_top_reg.h"
#include "errors.h"

// AES operation modes.
#define AES_OP_ENCRYPT   0x1u
#define AES_OP_DECRYPT   0x2u
#define AES_MODE_ECB     0x01u
#define AES_MODE_CBC     0x02u
#define AES_KEYLEN_128   0x1u

// Timeout for AES status polling.
#define AES_TIMEOUT  1000000

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

static int wait_idle(void)
{
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        AES_STATUS_reg_u s;
        s.val = mmio_read32(AES_STATUS_REG_ADDR);
        if (s.f.idle) return 0;
    }
    return -1;
}

static int wait_input_ready(void)
{
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        AES_STATUS_reg_u s;
        s.val = mmio_read32(AES_STATUS_REG_ADDR);
        if (s.f.input_ready) return 0;
    }
    return -1;
}

static int wait_output_valid(void)
{
    for (int i = 0; i < AES_TIMEOUT; ++i) {
        AES_STATUS_reg_u s;
        s.val = mmio_read32(AES_STATUS_REG_ADDR);
        if (s.f.output_valid) return 0;
    }
    return -1;
}

// Write CTRL_SHADOWED (must be written twice for shadowed register).
static void write_ctrl(uint32_t val)
{
    mmio_write32(AES_CTRL_SHADOWED_REG_ADDR, val);
    mmio_write32(AES_CTRL_SHADOWED_REG_ADDR, val);
}

static void write_key_128(const uint8_t *key)
{
    // KEY_SHARE0: actual key in first 4 words, zero-fill rest.
    for (int i = 0; i < 4; ++i) {
        uint32_t w = (uint32_t)key[i * 4]          |
                     ((uint32_t)key[i * 4 + 1] << 8)  |
                     ((uint32_t)key[i * 4 + 2] << 16) |
                     ((uint32_t)key[i * 4 + 3] << 24);
        mmio_write32(AES_KEY_SHARE0_0__REG_ADDR + (uint32_t)(i * 4), w);
    }
    for (int i = 4; i < 8; ++i) {
        mmio_write32(AES_KEY_SHARE0_0__REG_ADDR + (uint32_t)(i * 4), 0u);
    }

    // KEY_SHARE1: all zeros (no masking).
    for (int i = 0; i < 8; ++i) {
        mmio_write32(AES_KEY_SHARE1_0__REG_ADDR + (uint32_t)(i * 4), 0u);
    }
}

static void write_iv(const uint8_t *iv)
{
    for (int i = 0; i < 4; ++i) {
        uint32_t w = (uint32_t)iv[i * 4]          |
                     ((uint32_t)iv[i * 4 + 1] << 8)  |
                     ((uint32_t)iv[i * 4 + 2] << 16) |
                     ((uint32_t)iv[i * 4 + 3] << 24);
        mmio_write32(AES_IV_0__REG_ADDR + (uint32_t)(i * 4), w);
    }
}

static void write_data_in(const uint8_t *in)
{
    for (int i = 0; i < 4; ++i) {
        uint32_t w = (uint32_t)in[i * 4]          |
                     ((uint32_t)in[i * 4 + 1] << 8)  |
                     ((uint32_t)in[i * 4 + 2] << 16) |
                     ((uint32_t)in[i * 4 + 3] << 24);
        mmio_write32(AES_DATA_IN_0__REG_ADDR + (uint32_t)(i * 4), w);
    }
}

static void read_data_out(uint8_t *out)
{
    for (int i = 0; i < 4; ++i) {
        uint32_t w = mmio_read32(AES_DATA_OUT_0__REG_ADDR + (uint32_t)(i * 4));
        out[i * 4]     = (uint8_t)(w);
        out[i * 4 + 1] = (uint8_t)(w >> 8);
        out[i * 4 + 2] = (uint8_t)(w >> 16);
        out[i * 4 + 3] = (uint8_t)(w >> 24);
    }
}

static void aes_cleanup(void)
{
    AES_CTRL_SHADOWED_reg_u ctrl = {.val = 0};
    ctrl.f.operation = AES_OP_DECRYPT;
    ctrl.f.mode = AES_MODE_ECB;
    ctrl.f.key_len = AES_KEYLEN_128;
    ctrl.f.manual_operation = 1;
    write_ctrl(ctrl.val);

    AES_TRIGGER_reg_u trig = {.val = 0};
    trig.f.key_iv_data_in_clear = 1;
    trig.f.data_out_clear = 1;
    mmio_write32(AES_TRIGGER_REG_ADDR, trig.val);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int aes_init(void)
{
    // Release AES from SW reset.
    uint32_t rst = mmio_read32(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR);
    rst |= SEP_RESET_CTRL_SW_RESET_N_AES_SW_RST_N_MASK;
    mmio_write32(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR, rst);
    __asm__ volatile("fence" ::: "memory");

    if (!(mmio_read32(SEP_RESET_CTRL_SW_RESET_N_REG_ADDR) &
          SEP_RESET_CTRL_SW_RESET_N_AES_SW_RST_N_MASK)) {
        simputs("AES_RST_FAIL\n");
        return -1;
    }

    return 0;
}

int aes128cbc_decrypt(uint8_t *data, uint32_t len,
                      const uint8_t *key, const uint8_t *iv)
{
    if (len == 0u || (len & 0xFu) != 0u) {
        return -1;  // Must be non-zero and multiple of 16.
    }

    // Configure: DEC, CBC, AES-128, automatic.
    AES_CTRL_SHADOWED_reg_u ctrl = {.val = 0};
    ctrl.f.operation = AES_OP_DECRYPT;
    ctrl.f.mode = AES_MODE_CBC;
    ctrl.f.key_len = AES_KEYLEN_128;
    ctrl.f.sideload = 0;
    ctrl.f.manual_operation = 0;
    write_ctrl(ctrl.val);

    if (wait_idle() != 0) goto fail;

    write_key_128(key);

    if (wait_idle() != 0) goto fail;

    write_iv(iv);

    // Process each 16-byte block.
    uint32_t blocks = len >> 4;
    for (uint32_t b = 0; b < blocks; ++b) {
        if (wait_input_ready() != 0) goto fail;

        uint8_t *blk = data + b * 16u;
        write_data_in(blk);

        if (wait_output_valid() != 0) goto fail;

        read_data_out(blk);  // Decrypt in-place.
    }

    aes_cleanup();
    return 0;

fail:
    simputs("AES_DEC_FAIL\n");
    aes_cleanup();
    return -1;
}
