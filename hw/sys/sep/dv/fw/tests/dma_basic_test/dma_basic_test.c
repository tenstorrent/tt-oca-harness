// SPDX-License-Identifier: Apache-2.0
//
// SEP Secure-DMA basic-breadth firmware test (OSS rep DMA basic breadth). OCAH provenance:
// uvm_tests/dma sep_dma_uvm_reg_rw / reg_reset / cfg_regwen / range_regwen /
// addr_fixed / addr_wrap / addr_combo / mem_copy(width sweep) / err_opcode.
//
// EL2 firmware drives the Secure DMA (sep_dma.h, base 0x1080_0000) over the CPU
// LSU and proves the DMA CSR + copy-datapath basic contracts on bare sep. The
// transfers are SRAM->SRAM (DMA master -> SEP local xbar -> SRAM). Distinct from
// the Phase-1 DMA trio (dma_hash SHA-256 + SRAM->DCCM + IRQ; dma_cpu_contention
// mid-flight BUSY + dual-master; spi_ot_dma_rx lsio handshake): DMA basic breadth adds the
// CSR/REGWEN breadth + address-mode/width matrix + one opcode-error.
//
// main() returns the error count; start.S turns 0 -> PASS magic / non-zero ->
// FAIL magic on the 0x8000_0000 mailbox. Every checker logs a positive PASS line
// so the kept log is auditable (absence of FAIL is not evidence, AGENTS.md §7/§9).
//
// Checks:
//   CHK-RESET      : DMA config registers read their documented reset values.
//   CHK-CFG-REGWEN : CFG_REGWEN auto-locks (0x9) while BUSY -> a config write is
//                    rejected; unlocks (0x6) when idle -> the write then lands.
//   CHK-RANGE-REGWEN: RANGE_VALID=0 gates a transfer (RANGE_VALID_ERROR); then a
//                    full valid range is locked via RANGE_REGWEN rw0c (0x9) and a
//                    range-register write is rejected (one-way until reset).
//   CHK-COPY-MODE  : SRAM->SRAM data integrity per address mode with a per-mode
//                    expected image + untouched-neighbor: INCR linear, FIXED-src
//                    replicates, FIXED-dst overwrites one location, WRAP (chunk <
//                    total) accumulates num_chunks copies.
//   CHK-WIDTH      : copy integrity for 1B/2B/4B transfer widths.
//   CHK-DONE-RW1C  : STATUS.done observed -> W1C -> reads back 0 (polled status).
//   CHK-ERR-OPCODE : invalid opcode 0xF -> ERROR_CODE.opcode_error + STATUS.error;
//                    W1C clear; a subsequent good copy recovers.
//   CHK-NONVAC     : firmware error count 0 + boot scoreboard PASS banner.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"

#define SRC_BASE   0x10000000u   // SEP SRAM
#define DST_BASE   0x10000800u   // +2 KiB, no overlap with the 1 KiB busy-lock copy
#define ASID_OT_BOTH (SEP_DMA_ASID_OT | (SEP_DMA_ASID_OT << 4))
#define DONE_OR_ERR (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR)
#define STATUS_RW1C (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR | SEP_DMA_STATUS_CHUNK_DONE)
// Bounded so a transfer that never completes fails its checker (returns a STATUS
// with neither DONE nor ERROR) instead of wedging the whole run on one poll. A
// real 256 B copy completes in well under this many CSR-read iterations.
#define POLL_ITERS 4000

static inline uint32_t rd(uint32_t a) { return *(volatile uint32_t *)a; }
static inline void wr(uint32_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

// Program + start one transfer (caller has set the locked full range), poll until
// DONE or ERROR (robust against BUSY-assert latency), and return final STATUS.
static uint32_t dma_run(uint32_t src, uint32_t dst, uint32_t total, uint32_t chunk,
                        uint32_t width, uint32_t src_cfg, uint32_t dst_cfg, uint32_t opcode)
{
    wr(SEP_DMA_SRC_ADDR_LO, src);
    wr(SEP_DMA_SRC_ADDR_HI, 0);
    wr(SEP_DMA_DST_ADDR_LO, dst);
    wr(SEP_DMA_DST_ADDR_HI, 0);
    wr(SEP_DMA_ADDR_SPACE_ID, ASID_OT_BOTH);
    wr(SEP_DMA_TRANSFER_WIDTH, width);
    wr(SEP_DMA_TOTAL_DATA_SIZE, total);
    wr(SEP_DMA_CHUNK_DATA_SIZE, chunk);
    wr(SEP_DMA_SRC_CONFIG, src_cfg);
    wr(SEP_DMA_DST_CONFIG, dst_cfg);
    wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL | opcode);

    uint32_t st = 0;
    int t = POLL_ITERS;
    do {
        st = rd(SEP_DMA_STATUS);
    } while (!(st & DONE_OR_ERR) && --t > 0);
    return st;
}

// Multi-chunk transfer (chunk < total). In pure memory-to-memory mode the Secure
// DMA completes ONE chunk per GO (it raises CHUNK_DONE and drops BUSY, with no
// LSIO handshake wired for SRAM on bare sep), so firmware paces the chunks: clear
// CHUNK_DONE and re-GO with INITIAL_TRANSFER=0 until the final chunk raises DONE.
// Returns the final STATUS (DONE on success, ERROR, or the last poll on timeout).
static uint32_t dma_run_chunked(uint32_t src, uint32_t dst, uint32_t total, uint32_t chunk,
                                uint32_t width, uint32_t src_cfg, uint32_t dst_cfg,
                                uint32_t opcode)
{
    wr(SEP_DMA_SRC_ADDR_LO, src);
    wr(SEP_DMA_SRC_ADDR_HI, 0);
    wr(SEP_DMA_DST_ADDR_LO, dst);
    wr(SEP_DMA_DST_ADDR_HI, 0);
    wr(SEP_DMA_ADDR_SPACE_ID, ASID_OT_BOTH);
    wr(SEP_DMA_TRANSFER_WIDTH, width);
    wr(SEP_DMA_TOTAL_DATA_SIZE, total);
    wr(SEP_DMA_CHUNK_DATA_SIZE, chunk);
    wr(SEP_DMA_SRC_CONFIG, src_cfg);
    wr(SEP_DMA_DST_CONFIG, dst_cfg);

    uint32_t st = 0;
    uint32_t initial = SEP_DMA_CTRL_INITIAL;
    for (uint32_t guard = 0; guard < 64; guard++) {  // bounded chunk count
        wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | initial | opcode);
        int t = POLL_ITERS;
        do {
            st = rd(SEP_DMA_STATUS);
        } while (!(st & (DONE_OR_ERR | SEP_DMA_STATUS_CHUNK_DONE)) && --t > 0);
        if (st & (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR)) {
            return st;                       // whole transfer finished (or errored)
        }
        if (!(st & SEP_DMA_STATUS_CHUNK_DONE)) {
            return st;                       // timed out with no progress
        }
        wr(SEP_DMA_STATUS, SEP_DMA_STATUS_CHUNK_DONE);  // arm the next chunk
        initial = 0;
    }
    return st;
}

static void fill_src_words(uint32_t n)
{
    volatile uint32_t *s = (volatile uint32_t *)SRC_BASE;
    uint32_t lfsr = 0x1234567u;
    for (uint32_t i = 0; i < n; i++) {
        lfsr = lfsr * 1664525u + 1013904223u;
        s[i] = lfsr;
    }
}

// Clear ``n`` destination words to a sentinel so untouched-neighbor checks are real.
static void clear_dst_words(uint32_t n, uint32_t sentinel)
{
    volatile uint32_t *d = (volatile uint32_t *)DST_BASE;
    for (uint32_t i = 0; i < n; i++) {
        d[i] = sentinel;
    }
}

// ---- CHK-RESET: read the documented reset values (call FIRST, before any write) ----
static int chk_reset(void)
{
    int e = 0;
    struct { const char *name; uint32_t addr; uint32_t exp; } regs[] = {
        {"TRANSFER_WIDTH", SEP_DMA_TRANSFER_WIDTH, 0x2u},
        {"CONTROL",        SEP_DMA_CONTROL,        0x0u},
        {"SRC_CONFIG",     SEP_DMA_SRC_CONFIG,     0x0u},
        {"DST_CONFIG",     SEP_DMA_DST_CONFIG,     0x0u},
        {"CFG_REGWEN",     SEP_DMA_CFG_REGWEN,     SEP_DMA_REGWEN_UNLOCKED},
        {"RANGE_REGWEN",   SEP_DMA_RANGE_REGWEN,   SEP_DMA_REGWEN_UNLOCKED},
        {"RANGE_VALID",    SEP_DMA_RANGE_VALID,    0x0u},
        {"STATUS",         SEP_DMA_STATUS,         0x0u},
        {"ERROR_CODE",     SEP_DMA_ERROR_CODE,     0x0u},
        {"SRC_ADDR_LO",    SEP_DMA_SRC_ADDR_LO,    0x0u},
        {"DST_ADDR_LO",    SEP_DMA_DST_ADDR_LO,    0x0u},
        {"TOTAL_DATA_SIZE", SEP_DMA_TOTAL_DATA_SIZE, 0x0u},
        {"CHUNK_DATA_SIZE", SEP_DMA_CHUNK_DATA_SIZE, 0x0u},
    };
    for (unsigned i = 0; i < sizeof(regs) / sizeof(regs[0]); i++) {
        uint32_t got = rd(regs[i].addr);
        if (got != regs[i].exp) {
            sep_mbx_puts("FAIL: CHK-RESET ");
            sep_mbx_puts(regs[i].name);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(got);
            sep_mbx_putc('\n');
            e++;
        }
    }
    if (!e) {
        sep_mbx_puts("CHK-RESET PASS: DMA config registers at documented reset values\n");
    }
    return e;
}

// ---- CHK-CFG-REGWEN: HW auto-lock while BUSY rejects a config write ----
static int chk_cfg_regwen(void)
{
    int e = 0;
    // A 256 B copy (64 beats) stays BUSY long enough for the CPU to observe the
    // lock on its very next CSR read, without bloating sim time.
    const uint32_t len = 0x100u;
    fill_src_words(len / 4);
    wr(SEP_DMA_SRC_ADDR_LO, SRC_BASE);
    wr(SEP_DMA_SRC_ADDR_HI, 0);
    wr(SEP_DMA_DST_ADDR_LO, DST_BASE);
    wr(SEP_DMA_DST_ADDR_HI, 0);
    wr(SEP_DMA_ADDR_SPACE_ID, ASID_OT_BOTH);
    wr(SEP_DMA_TRANSFER_WIDTH, SEP_DMA_WIDTH_4B);
    wr(SEP_DMA_TOTAL_DATA_SIZE, len);
    wr(SEP_DMA_CHUNK_DATA_SIZE, len);
    wr(SEP_DMA_SRC_CONFIG, SEP_DMA_CFG_INCR);
    wr(SEP_DMA_DST_CONFIG, SEP_DMA_CFG_INCR);
    wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL | SEP_DMA_OPCODE_COPY);

    // Sample BUSY + CFG_REGWEN immediately; the copy must still be running.
    uint32_t st = rd(SEP_DMA_STATUS);
    uint32_t regwen_busy = rd(SEP_DMA_CFG_REGWEN);
    if (!(st & SEP_DMA_STATUS_BUSY)) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN copy finished too fast to observe BUSY\n");
        return e + 1;
    }
    if (regwen_busy != SEP_DMA_REGWEN_LOCKED) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN not locked while BUSY, got ");
        sep_mbx_puthex(regwen_busy);
        sep_mbx_putc('\n');
        e++;
    }
    // A config write while locked must be rejected (SRC_ADDR_LO holds SRC_BASE).
    wr(SEP_DMA_SRC_ADDR_LO, 0xDEADBEEFu);
    uint32_t after = rd(SEP_DMA_SRC_ADDR_LO);
    if (after != SRC_BASE) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN config write not rejected while locked, got ");
        sep_mbx_puthex(after);
        sep_mbx_putc('\n');
        e++;
    }
    // Drain the copy.
    int t = POLL_ITERS;
    do { st = rd(SEP_DMA_STATUS); } while (!(st & DONE_OR_ERR) && --t > 0);
    wr(SEP_DMA_STATUS, STATUS_RW1C);

    uint32_t regwen_idle = rd(SEP_DMA_CFG_REGWEN);
    if (regwen_idle != SEP_DMA_REGWEN_UNLOCKED) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN not unlocked when idle, got ");
        sep_mbx_puthex(regwen_idle);
        sep_mbx_putc('\n');
        e++;
    }
    // The same config write now lands.
    wr(SEP_DMA_SRC_ADDR_LO, 0xDEADBEEFu);
    if (rd(SEP_DMA_SRC_ADDR_LO) != 0xDEADBEEFu) {
        sep_mbx_puts("FAIL: CHK-CFG-REGWEN config write rejected while idle\n");
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-CFG-REGWEN PASS: locked 0x9 while BUSY (write rejected), "
                     "unlocked 0x6 when idle (write lands)\n");
    }
    return e;
}

// ---- CHK-RANGE-REGWEN: range gating + rw0c lock (one-way until reset) ----
static int chk_range_regwen(void)
{
    int e = 0;
    // (a) Range gating: RANGE_VALID still 0 (reset) -> a transfer errors.
    uint32_t st = dma_run(SRC_BASE, DST_BASE, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                          SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, SEP_DMA_OPCODE_COPY);
    uint32_t err = rd(SEP_DMA_ERROR_CODE);
    if (!(st & SEP_DMA_STATUS_ERROR) || !(err & SEP_DMA_ERR_RANGE_VALID)) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN RANGE_VALID=0 did not gate (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    wr(SEP_DMA_STATUS, STATUS_RW1C);  // clear the error

    // (b) Program a full valid range, then lock it via RANGE_REGWEN rw0c.
    wr(SEP_DMA_ENABLED_RANGE_BASE, 0x0u);
    wr(SEP_DMA_ENABLED_RANGE_LIMIT, 0xFFFFFFFFu);
    wr(SEP_DMA_RANGE_VALID, 0x1u);
    wr(SEP_DMA_RANGE_REGWEN, SEP_DMA_REGWEN_LOCKED);
    if (rd(SEP_DMA_RANGE_REGWEN) != SEP_DMA_REGWEN_LOCKED) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN did not latch locked\n");
        e++;
    }
    // (c) A range-register write must now be rejected (one-way until reset).
    wr(SEP_DMA_ENABLED_RANGE_BASE, 0xCAFE0000u);
    if (rd(SEP_DMA_ENABLED_RANGE_BASE) != 0x0u) {
        sep_mbx_puts("FAIL: CHK-RANGE-REGWEN range write not rejected after lock\n");
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-RANGE-REGWEN PASS: RANGE_VALID=0 gated (range_valid_error), "
                     "full range locked rw0c (range write rejected)\n");
    }
    return e;
}

// Verify ``n`` destination words match ``expect[i]`` and ``DST[n]`` is the sentinel.
static int check_words(const uint32_t *expect, uint32_t n, uint32_t sentinel, const char *tag)
{
    volatile uint32_t *d = (volatile uint32_t *)DST_BASE;
    for (uint32_t i = 0; i < n; i++) {
        if (d[i] != expect[i]) {
            sep_mbx_puts("FAIL: ");
            sep_mbx_puts(tag);
            sep_mbx_puts(" word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(d[i]);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(expect[i]);
            sep_mbx_putc('\n');
            return 1;
        }
    }
    if (d[n] != sentinel) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(tag);
        sep_mbx_puts(" neighbor word clobbered ");
        sep_mbx_puthex(d[n]);
        sep_mbx_putc('\n');
        return 1;
    }
    return 0;
}

// Run one address-mode copy and verify its expected image + neighbor. Always logs
// the STATUS + ERROR_CODE on a no-clean-DONE failure (no silent short-circuit), so
// the kept log names which mode failed and why.
static int run_mode(const char *tag, uint32_t total, uint32_t chunk,
                    uint32_t src_cfg, uint32_t dst_cfg,
                    const uint32_t *exp, uint32_t nexp, uint32_t sentinel)
{
    clear_dst_words(5, sentinel);
    uint32_t st = (chunk < total)
        ? dma_run_chunked(SRC_BASE, DST_BASE, total, chunk, SEP_DMA_WIDTH_4B,
                          src_cfg, dst_cfg, SEP_DMA_OPCODE_COPY)
        : dma_run(SRC_BASE, DST_BASE, total, chunk, SEP_DMA_WIDTH_4B,
                  src_cfg, dst_cfg, SEP_DMA_OPCODE_COPY);
    int bad = 0;
    if (!(st & SEP_DMA_STATUS_DONE) || (st & SEP_DMA_STATUS_ERROR)) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(tag);
        sep_mbx_puts(" no clean DONE, status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(rd(SEP_DMA_ERROR_CODE));
        sep_mbx_putc('\n');
        bad = 1;
    } else if (check_words(exp, nexp, sentinel, tag)) {
        bad = 1;
    }
    wr(SEP_DMA_STATUS, STATUS_RW1C);
    return bad;
}

// ---- CHK-COPY-MODE: per address-mode expected image + neighbor ----
static int chk_copy_mode(void)
{
    int e = 0;
    const uint32_t SENT = 0xA5A5A5A5u;
    volatile uint32_t *s = (volatile uint32_t *)SRC_BASE;
    uint32_t exp[4];

    fill_src_words(4);  // s[0..3] deterministic

    // (1) INCR/INCR linear copy: dst[i] = src[i].
    exp[0] = s[0]; exp[1] = s[1]; exp[2] = s[2]; exp[3] = s[3];
    e += run_mode("CHK-COPY-MODE INCR", 0x10u, 0x10u,
                  SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, exp, 4, SENT);

    // (2) FIXED src (re-read in place) + INCR dst: dst[i] = src[0] (replicate).
    exp[0] = s[0]; exp[1] = s[0]; exp[2] = s[0]; exp[3] = s[0];
    e += run_mode("CHK-COPY-MODE FIXED-src", 0x10u, 0x10u,
                  SEP_DMA_CFG_FIXED, SEP_DMA_CFG_INCR, exp, 4, SENT);

    // (3) INCR src + FIXED dst (overwrite in place): dst[0] = src[3], dst[1] untouched.
    exp[0] = s[3];
    e += run_mode("CHK-COPY-MODE FIXED-dst", 0x10u, 0x10u,
                  SEP_DMA_CFG_INCR, SEP_DMA_CFG_FIXED, exp, 1, SENT);

    // (4) WRAP src (chunk < total) + INCR dst: total 16 / chunk 8 -> 2 chunks of
    // 2 words; the source wraps to its start each chunk, so dst = [s0,s1,s0,s1].
    exp[0] = s[0]; exp[1] = s[1]; exp[2] = s[0]; exp[3] = s[1];
    e += run_mode("CHK-COPY-MODE WRAP-src", 0x10u, 0x08u,
                  SEP_DMA_CFG_WRAP_CHUNK, SEP_DMA_CFG_INCR, exp, 4, SENT);

    if (!e) {
        sep_mbx_puts("CHK-COPY-MODE PASS: INCR linear / FIXED-src replicate / "
                     "FIXED-dst overwrite / WRAP chunk-accumulate, neighbors intact\n");
    }
    return e;
}

// ---- CHK-WIDTH: INCR copy integrity at 1B / 2B / 4B ----
static int chk_width(void)
{
    int e = 0;
    const uint32_t SENT = 0x5A5A5A5Au;
    const uint32_t bytes = 16u;
    volatile uint8_t *sb = (volatile uint8_t *)SRC_BASE;
    volatile uint8_t *db = (volatile uint8_t *)DST_BASE;
    uint32_t widths[3] = {SEP_DMA_WIDTH_1B, SEP_DMA_WIDTH_2B, SEP_DMA_WIDTH_4B};

    fill_src_words(bytes / 4);
    for (int w = 0; w < 3; w++) {
        clear_dst_words(bytes / 4 + 1, SENT);
        uint32_t st = dma_run(SRC_BASE, DST_BASE, bytes, bytes, widths[w],
                              SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, SEP_DMA_OPCODE_COPY);
        int bad = (!(st & SEP_DMA_STATUS_DONE) || (st & SEP_DMA_STATUS_ERROR));
        for (uint32_t i = 0; i < bytes && !bad; i++) {
            if (db[i] != sb[i]) bad = 1;
        }
        if (bad) {
            sep_mbx_puts("FAIL: CHK-WIDTH width-enc ");
            sep_mbx_puthex(widths[w]);
            sep_mbx_puts(" copy mismatch (status ");
            sep_mbx_puthex(st);
            sep_mbx_puts(")\n");
            e++;
        }
        wr(SEP_DMA_STATUS, STATUS_RW1C);
    }
    if (!e) {
        sep_mbx_puts("CHK-WIDTH PASS: 1B/2B/4B transfer-width copies byte-exact\n");
    }
    return e;
}

// ---- CHK-DONE-RW1C: STATUS.done observed -> W1C -> reads back 0 ----
static int chk_done_rw1c(void)
{
    int e = 0;
    const uint32_t SENT = 0x33333333u;
    fill_src_words(4);
    clear_dst_words(5, SENT);
    uint32_t st = dma_run(SRC_BASE, DST_BASE, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                          SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, SEP_DMA_OPCODE_COPY);
    if (!(st & SEP_DMA_STATUS_DONE)) {
        sep_mbx_puts("FAIL: CHK-DONE-RW1C STATUS.done not observed\n");
        return e + 1;
    }
    wr(SEP_DMA_STATUS, SEP_DMA_STATUS_DONE);   // W1C
    uint32_t after = rd(SEP_DMA_STATUS);
    if (after & SEP_DMA_STATUS_DONE) {
        sep_mbx_puts("FAIL: CHK-DONE-RW1C STATUS.done did not clear, got ");
        sep_mbx_puthex(after);
        sep_mbx_putc('\n');
        e++;
    }
    if (!e) {
        sep_mbx_puts("CHK-DONE-RW1C PASS: STATUS.done set then W1C-cleared to 0\n");
    }
    return e;
}

// ---- CHK-ERR-OPCODE: invalid opcode -> opcode_error -> clear -> recovery ----
static int chk_err_opcode(void)
{
    int e = 0;
    const uint32_t SENT = 0xC3C3C3C3u;
    fill_src_words(4);
    uint32_t st = dma_run(SRC_BASE, DST_BASE, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                          SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, SEP_DMA_OPCODE_INVALID);
    uint32_t err = rd(SEP_DMA_ERROR_CODE);
    // Exclusive: ONLY opcode_error must be set (no other ERROR_CODE bit), matching
    // the OCAH err_opcode error-exclusivity check.
    if (!(st & SEP_DMA_STATUS_ERROR) || err != SEP_DMA_ERR_OPCODE) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE invalid opcode did not set opcode_error "
                     "exclusively (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    if (st & SEP_DMA_STATUS_DONE) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE STATUS.done set on an errored transfer\n");
        e++;
    }
    wr(SEP_DMA_STATUS, STATUS_RW1C);  // clear error

    // Recovery: a subsequent good COPY succeeds with no error.
    clear_dst_words(5, SENT);
    st = dma_run(SRC_BASE, DST_BASE, 0x10u, 0x10u, SEP_DMA_WIDTH_4B,
                 SEP_DMA_CFG_INCR, SEP_DMA_CFG_INCR, SEP_DMA_OPCODE_COPY);
    err = rd(SEP_DMA_ERROR_CODE);
    if (!(st & SEP_DMA_STATUS_DONE) || (st & SEP_DMA_STATUS_ERROR) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-OPCODE recovery copy did not succeed (status ");
        sep_mbx_puthex(st);
        sep_mbx_puts(" err ");
        sep_mbx_puthex(err);
        sep_mbx_puts(")\n");
        e++;
    }
    wr(SEP_DMA_STATUS, STATUS_RW1C);
    if (!e) {
        sep_mbx_puts("CHK-ERR-OPCODE PASS: opcode 0xF -> opcode_error EXCLUSIVE + "
                     "STATUS.error, W1C clear, recovery copy OK\n");
    }
    return e;
}

int main(void)
{
    int errors = 0;

    sep_outbound_filter_init();        // open the 0x8000_0000 console window
    sep_mbx_puts("SEP DMA basic test\n");

    errors += chk_reset();          // must run before any DMA write
    errors += chk_range_regwen();   // proves gating, then locks a full valid range
                                    // that all later transfers rely on
    errors += chk_cfg_regwen();
    errors += chk_copy_mode();
    errors += chk_width();
    errors += chk_done_rw1c();
    errors += chk_err_opcode();

    if (errors == 0) {
        sep_mbx_puts("PASS: DMA basic -- reset/cfg-regwen/range-regwen/copy-mode/"
                     "width/done-rw1c/err-opcode all OK\n");
    }
    return errors;
}
