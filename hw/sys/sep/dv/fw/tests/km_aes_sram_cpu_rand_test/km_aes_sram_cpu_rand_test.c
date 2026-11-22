// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// The SEP CPU moves SEP SRAM blocks through AES under a key that it loads into
// the Key Manager (KM) and transfers to AES.
//
// The host (cocotb/tests/km/sep_km_aes_sram_cpu_rand_test.py) draws every value
// and patches it into the parameter block g_prm of the DTCM image: the block
// count n, the SRAM region and guard addresses, the two CTRL_SHADOWED words, the
// guard, plaintext and fill words, the KM key and a dummy software key. The
// firmware holds no expected value and grades nothing. It prints what the DUT
// returns as console records (sep_console_rec.h), and the host grades them.
//
// Procedure:
//  1. Echo the parameter header and the CRC-32C of each key (no key word is
//     printed).
//  2. Wait for fuse sense, bring up the entropy stack, release AES and the KM
//     from software reset, and wait for RESP_KM_READY.
//  3. CMD_KEY_LOAD of the patched key with destination AES, then
//     CMD_KEY_TRANSFER of the returned handle to AES. Each command prints its
//     return code and return argument.
//  4. Write the guard, source, encrypt-fill and decrypt-fill words to SRAM and
//     print their readback.
//  5. Decoy leg: CTRL_SHADOWED (written twice) with the encrypt word and
//     SIDELOAD cleared, the dummy key to KEY_SHARE0 and zero to KEY_SHARE1, and
//     source block 0 through AES; the output is printed, not stored.
//  6. Encrypt leg: CTRL_SHADOWED (written twice) with the patched encrypt word,
//     the dummy key to KEY_SHARE0 and zero to KEY_SHARE1, then for each block a
//     CPU load from the source region, DATA_IN, OUTPUT_VALID, DATA_OUT and a CPU
//     store to the encrypt region. Decrypt leg: the same from the encrypt
//     region to the decrypt region. Each leg prints its CTRL_SHADOWED readback
//     and its OUTPUT_VALID poll counts.
//  7. Print the readback of every region and guard word.
//
// main() returns 0 only when every set-up step, both KM commands and the three AES
// legs return 0; crt0.s turns 0 into the PASS magic.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_efuse.h"
#include "sep_entropy.h"
#include "sep_aes_init.h"
#include "aes_test_util.h"
#include "sep_console_rec.h"
#include "km_mailbox.h"

#define PRM_MAGIC 0xC5A3E19Bu
#define N_MAX 8u
#define BLOCK_WORDS 4u
#define REGION_MAX (N_MAX * BLOCK_WORDS)
#define N_GUARDS 6u
#define GUARD_WORDS 2u
#define KEY_WORDS 8u
#define SENSE_WAIT_LIMIT 1000000

enum {
    P_MAGIC = 0,
    P_SEED,
    P_N,
    P_SRC,                       // source region base (plaintext)
    P_ENC,                       // encrypt destination base
    P_DEC,                       // decrypt destination base
    P_CTRL_ENC,                  // CTRL_SHADOWED word of the encrypt leg
    P_CTRL_DEC,                  // CTRL_SHADOWED word of the decrypt leg
    P_GADDR,                     // N_GUARDS guard addresses
    P_GVAL = P_GADDR + N_GUARDS, // GUARD_WORDS words per guard
    P_HDR_END = P_GVAL + N_GUARDS * GUARD_WORDS,
    P_KEY = P_HDR_END,              // KM key, KEY_WORDS words
    P_DKEY = P_KEY + KEY_WORDS,     // dummy software key
    P_PT = P_DKEY + KEY_WORDS,      // REGION_MAX plaintext words
    P_EFILL = P_PT + REGION_MAX,    // encrypt region fill
    P_DFILL = P_EFILL + REGION_MAX, // decrypt region fill
    P_WORDS = P_DFILL + REGION_MAX,
};

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
};

static void copy_prm(uint32_t *dst, uint32_t idx, uint32_t count) {
    for (uint32_t i = 0; i < count; i++) dst[i] = g_prm[idx + i];
}

static void sram_write(uint32_t addr, const uint32_t *w, uint32_t count) {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    for (uint32_t i = 0; i < count; i++) p[i] = w[i];
    __asm__ volatile("fence" ::: "memory");
}

static void sram_read(uint32_t addr, uint32_t *w, uint32_t count) {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    __asm__ volatile("fence" ::: "memory");
    for (uint32_t i = 0; i < count; i++) w[i] = p[i];
}

// "INFO-KMAES-WORDS LOG stage=<s> part=<p> i=<idx> w0=.. w<k-1>=..", at most 4 words a line.
static void put_words(const char *stage, const char *part, const uint32_t *w, uint32_t count) {
    static const char *const keys[BLOCK_WORDS] = {"w0", "w1", "w2", "w3"};
    for (uint32_t base = 0; base < count; base += BLOCK_WORDS) {
        rec_info("KMAES-WORDS");
        rec_str("stage", stage);
        rec_str("part", part);
        rec_num("i", base);
        for (uint32_t k = 0; k < BLOCK_WORDS && base + k < count; k++)
            rec_hex(keys[k], w[base + k]);
        rec_end();
    }
}

// "INFO-KMAES-CMD LOG cmd=<c> rc=0x.. arg=0x.."
static void put_cmd(const char *cmd, int rc, uint32_t arg) {
    rec_info("KMAES-CMD");
    rec_str("cmd", cmd);
    rec_hex("rc", (uint32_t)rc);
    rec_hex("arg", arg);
    rec_end();
}

static void put_region(const char *stage, const char *part, uint32_t addr, uint32_t count) {
    uint32_t w[REGION_MAX];
    sram_read(addr, w, count);
    put_words(stage, part, w, count);
}

static void put_guards(const char *stage) {
    uint32_t w[N_GUARDS * GUARD_WORDS];
    for (uint32_t g = 0; g < N_GUARDS; g++)
        sram_read(g_prm[P_GADDR + g], &w[g * GUARD_WORDS], GUARD_WORDS);
    put_words(stage, "guard", w, N_GUARDS * GUARD_WORDS);
}

static void put_all_regions(const char *stage, uint32_t words) {
    put_region(stage, "src", g_prm[P_SRC], words);
    put_region(stage, "enc", g_prm[P_ENC], words);
    put_region(stage, "dec", g_prm[P_DEC], words);
    put_guards(stage);
}

static int sram_range_ok(uint32_t addr, uint32_t bytes) {
    return (addr & 3u) == 0u && addr >= SEP_TOP_SEP_SRAM_BASE_ADDR &&
           bytes <= SEP_TOP_SEP_SRAM_SIZE &&
           addr - SEP_TOP_SEP_SRAM_BASE_ADDR <= SEP_TOP_SEP_SRAM_SIZE - bytes;
}

static int params_ok(void) {
    uint32_t n = g_prm[P_N];
    if (g_prm[P_MAGIC] != PRM_MAGIC || n < 2u || n > N_MAX) return 0;
    uint32_t bytes = n * BLOCK_WORDS * 4u;
    if (!sram_range_ok(g_prm[P_SRC], bytes) || !sram_range_ok(g_prm[P_ENC], bytes) ||
        !sram_range_ok(g_prm[P_DEC], bytes))
        return 0;
    for (uint32_t g = 0; g < N_GUARDS; g++)
        if (!sram_range_ok(g_prm[P_GADDR + g], GUARD_WORDS * 4u)) return 0;
    return 1;
}

// Configure AES in the programmer's order: IDLE, CTRL_SHADOWED twice, IDLE,
// `key` to KEY_SHARE0 and zero to KEY_SHARE1, IDLE. Prints the CTRL_SHADOWED
// readback. Returns 0, or 1/4 for an IDLE timeout before/after CTRL_SHADOWED.
static int aes_config(const char *op, uint32_t ctrl, const uint32_t key[KEY_WORDS]) {
    if (wait_for_idle() != 0) return 1;
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl);
    if (wait_for_idle() != 0) return 4;
    for (uint32_t i = 0; i < KEY_WORDS; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), key[i]);
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0u);
    }
    if (wait_for_idle() != 0) return 4;

    rec_info("KMAES-CMD");
    rec_str("cmd", "ctrl");
    rec_str("op", op);
    rec_hex("rc", 0u);
    rec_hex("arg", READ_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR));
    rec_end();
    return 0;
}

// One block through AES: INPUT_READY, DATA_IN, OUTPUT_VALID, DATA_OUT. Returns
// 0, or 2/3 for an INPUT_READY or OUTPUT_VALID timeout; *polls counts the
// STATUS reads until OUTPUT_VALID.
static int aes_block(const uint32_t in[BLOCK_WORDS], uint32_t out[BLOCK_WORDS], uint32_t *polls) {
    if (wait_for_input_ready() != 0) return 2;
    write_data_in(in);
    *polls = 0u;
    for (;;) {
        aes__STATUS_t st = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        (*polls)++;
        if (st.f.OUTPUT_VALID) break;
        if (*polls >= (uint32_t)AES_WAIT_TIMEOUT) return 3;
    }
    read_data_out(out);
    return 0;
}

// Decoy leg: the encrypt word with SIDELOAD cleared, so AES keys from the
// software registers, and one block (SRC block 0) through AES. The output is
// printed and not stored. Returns as aes_config / aes_block.
static int aes_decoy(uint32_t ctrl_enc, uint32_t src, const uint32_t dkey[KEY_WORDS]) {
    aes__CTRL_SHADOWED_t ctrl = {.w = ctrl_enc};
    ctrl.f.SIDELOAD = 0;
    int rc = aes_config("decoy", ctrl.w, dkey);
    if (rc != 0) return rc;
    uint32_t in[BLOCK_WORDS], out[BLOCK_WORDS], polls;
    sram_read(src, in, BLOCK_WORDS);
    rc = aes_block(in, out, &polls);
    if (rc != 0) return rc;
    put_words("decoy", "out", out, BLOCK_WORDS);
    return 0;
}

// One AES leg: n blocks from src through AES to dst, the CPU doing every load
// and store. Returns as aes_config / aes_block.
static int aes_leg(const char *op, uint32_t ctrl, uint32_t src, uint32_t dst, uint32_t n,
                   const uint32_t dkey[KEY_WORDS]) {
    int rc = aes_config(op, ctrl, dkey);
    if (rc != 0) return rc;

    uint32_t pmin = 0xFFFFFFFFu, pmax = 0u, pfirst = 0u;
    for (uint32_t b = 0; b < n; b++) {
        uint32_t in[BLOCK_WORDS], out[BLOCK_WORDS], polls;
        sram_read(src + b * BLOCK_WORDS * 4u, in, BLOCK_WORDS);
        rc = aes_block(in, out, &polls);
        if (rc != 0) return rc;
        sram_write(dst + b * BLOCK_WORDS * 4u, out, BLOCK_WORDS);
        if (b == 0u) pfirst = polls;
        if (polls < pmin) pmin = polls;
        if (polls > pmax) pmax = polls;
    }
    rec_info("AES-SRAM-KM-CPU-LAT");
    rec_str("op", op);
    rec_num("blocks", n);
    rec_num("min", pmin);
    rec_num("max", pmax);
    rec_num("first", pfirst);
    rec_end();
    return 0;
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP KM AES SRAM CPU test\n");
    if (!params_ok()) {
        sep_mbx_puts("FAIL: parameter block not patched or out of range\n");
        return 1;
    }

    uint32_t hdr[P_HDR_END], key[KEY_WORDS], dkey[KEY_WORDS];
    copy_prm(hdr, 0u, P_HDR_END);
    copy_prm(key, P_KEY, KEY_WORDS);
    copy_prm(dkey, P_DKEY, KEY_WORDS);
    put_words("param", "hdr", hdr, P_HDR_END);
    rec_info("KMAES-WORDS");
    rec_str("stage", "param");
    rec_str("part", "keycrc");
    rec_hex("kcrc", km_crc32c_words(key, KEY_WORDS));
    rec_hex("dcrc", km_crc32c_words(dkey, KEY_WORDS));
    rec_end();

    rec_mark(0, "setup");
    int rc = sep_efuse_wait_sense_done(SENSE_WAIT_LIMIT);
    put_cmd("sense", rc, 0u);
    if (rc != 0) return 1;
    rc = sep_entropy_bringup();
    put_cmd("entropy", rc, 0u);
    if (rc != SEP_ENTROPY_OK) return 1;
    rc = sep_aes_sw_reset_release();
    put_cmd("aes_rst", rc, 0u);
    if (rc != 0) return 1;
    rc = km_release_reset();
    put_cmd("km_rst", rc, 0u);
    if (rc != 0) return 1;

    rec_mark(0, "km");
    rc = km_wait_ready();
    put_cmd("ready", rc, 0u);
    if (rc != 0) return 1;

    uint32_t load[2u + KEY_WORDS];
    uint32_t load_arg = 0u, xfer_arg = 0u;
    load[0] = KEY_WORDS - 1u;
    load[1] = KM_DEST_AES;
    for (uint32_t i = 0; i < KEY_WORDS; i++) load[2u + i] = key[i];
    rc = km_command(KM_CMD_KEY_LOAD, load, (uint8_t)(2u + KEY_WORDS), &load_arg);
    put_cmd("load", rc, load_arg);
    if (rc != 0) return 1;
    uint32_t xfer[2] = {(uint8_t)load_arg, KM_DEST_AES};
    rc = km_command(KM_CMD_KEY_TRANSFER, xfer, 2u, &xfer_arg);
    put_cmd("xfer", rc, xfer_arg);
    if (rc != 0) return 1;

    rec_mark(1, "kmaes");
    uint32_t n = g_prm[P_N];
    uint32_t words = n * BLOCK_WORDS;
    uint32_t buf[REGION_MAX];
    for (uint32_t g = 0; g < N_GUARDS; g++) {
        copy_prm(buf, P_GVAL + g * GUARD_WORDS, GUARD_WORDS);
        sram_write(g_prm[P_GADDR + g], buf, GUARD_WORDS);
    }
    copy_prm(buf, P_PT, words);
    sram_write(g_prm[P_SRC], buf, words);
    copy_prm(buf, P_EFILL, words);
    sram_write(g_prm[P_ENC], buf, words);
    copy_prm(buf, P_DFILL, words);
    sram_write(g_prm[P_DEC], buf, words);
    put_all_regions("pre", words);

    int xrc = aes_decoy(g_prm[P_CTRL_ENC], g_prm[P_SRC], dkey);
    put_cmd("aes_decoy", xrc, 0u);
    int erc = aes_leg("enc", g_prm[P_CTRL_ENC], g_prm[P_SRC], g_prm[P_ENC], n, dkey);
    put_cmd("aes_enc", erc, 0u);
    int drc =
        (erc == 0) ? aes_leg("dec", g_prm[P_CTRL_DEC], g_prm[P_ENC], g_prm[P_DEC], n, dkey) : -1;
    put_cmd("aes_dec", drc, 0u);

    rec_mark(0, "readback");
    put_all_regions("post", words);
    return (xrc != 0 || erc != 0 || drc != 0) ? 1 : 0;
}
