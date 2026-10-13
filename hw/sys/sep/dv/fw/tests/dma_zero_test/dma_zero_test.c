// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure DMA zero fill test. The CPU drives the Secure DMA zero fill
// (CONTROL.OPCODE 4) into SEP SRAM, DCCM and ICCM, the last two through the
// core's DMA slave port. ICCM is checked through a DMA copy back to SRAM,
// because a load from ICCM takes an access fault on this configuration.
//
// main() returns the error count; startup/crt0.s turns it into the PASS/FAIL
// magic on the mailbox. Every checker logs a positive PASS line, because the
// absence of a FAIL line is not evidence.
//
// Checks:
//   CHK-ZERO-SRAM       : a 4-byte-wide fill clears its words and a 1-byte-wide
//                         fill from an unaligned address clears its bytes; the
//                         neighbours keep their pattern.
//   CHK-ZERO-DCCM       : a 4-byte-wide fill clears its words of a DCCM buffer;
//                         the neighbours keep their pattern.
//   CHK-ZERO-ICCM       : after a pattern is copied to ICCM and a 4-byte-wide
//                         fill clears its inner words, a copy back to SRAM shows
//                         zeros inside and the pattern at both neighbours.
//   CHK-ZERO-TCM-NARROW : a 2-byte-wide fill into ICCM, which the core accepts
//                         only as whole words, ends in ERROR with BUS_ERROR
//                         alone and the exclusive host-path error in
//                         DMA_BUS_ERR_STATUS; after both clears, and before
//                         the next GO, DMA_BUS_ERR_STATUS reads 0, STATUS.ERROR
//                         reads 0 and ERROR_CODE reads 0; a 4-byte-wide fill
//                         then completes.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"

#define SRAM_BASE SEP_TOP_SEP_SRAM_BASE_ADDR
#define ASID_OT_BOTH \
    SEP_DMA_ASID_PAIR(SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset, \
                      SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset)
#define DONE_OR_ERR (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)
#define STATUS_RW1C \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)
// Bounded so a transfer that never completes fails its checker instead of
// wedging the run on one poll.
#define POLL_ITERS 4000

// Words each 4-byte-wide fill clears, between two pattern neighbours.
#define NWORDS 16u
#define SRAM_WORDS_BUF (SRAM_BASE + 0x1000u)
#define SRAM_BYTES_BUF (SRAM_BASE + 0x2000u)
#define SRAM_RET_BUF (SRAM_BASE + 0x3000u)
#define SRAM_PATTERN_BUF (SRAM_BASE + 0x4000u)
#define ICCM_ZERO_OFFSET 0x20000u
#define ICCM_ZERO_BASE (SEP_TOP_SEP_ICCM_BASE_ADDR + ICCM_ZERO_OFFSET)
_Static_assert(ICCM_ZERO_OFFSET + ((NWORDS + 2u) * 4u) <= SEP_TOP_SEP_ICCM_SIZE,
               "the ICCM zero window runs past the end of the instruction memory");
#define SENTINEL 0x1CC11CC1u

// Bytes 8..15 of the byte buffer stay outside the 1-byte-wide fill.
#define BYTE_FILL_OFFSET 1u
#define BYTE_FILL_LEN 7u

static volatile uint32_t dccm_buf[NWORDS + 2u];

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
}

// A word with no zero byte, distinct per index.
static uint32_t pattern(uint32_t i) {
    return 0xC3000000u | (0x00010101u * ((i % 0xFEu) + 1u));
}

static uint32_t dma_run(uint32_t opcode, uint32_t src, uint32_t dst, uint32_t total,
                        uint32_t width) {
    wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0);
    wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0);
    wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, ASID_OT_BOTH);
    wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, width);
    wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total);
    wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, total);
    wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, SECURE_DMA__SRC_CONFIG__INCREMENT_bm);
    wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, SECURE_DMA__DST_CONFIG__INCREMENT_bm);
    wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, SECURE_DMA__CONTROL__GO_bm |
                                                 SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                                                 (opcode << SECURE_DMA__CONTROL__OPCODE_bp));
    uint32_t st = 0;
    int t = POLL_ITERS;
    do {
        st = rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & DONE_OR_ERR) && --t > 0);
    return st;
}

static uint32_t zero_fill(uint32_t dst, uint32_t total, uint32_t width) {
    return dma_run(SEP_DMA_OPCODE_ZERO, 0, dst, total, width);
}

// A transfer that reached DONE with ERROR and ERROR_CODE clear; logs and counts otherwise.
static int expect_clean(const char *chk, const char *what, uint32_t st) {
    uint32_t err = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    if ((st & SECURE_DMA__STATUS__DONE_bm) && !(st & SECURE_DMA__STATUS__ERROR_bm) && err == 0) {
        return 0;
    }
    sep_mbx_puts("FAIL: ");
    sep_mbx_puts(chk);
    sep_mbx_puts(" ");
    sep_mbx_puts(what);
    sep_mbx_puts(" STATUS=");
    sep_mbx_puthex(st);
    sep_mbx_puts(" ERROR_CODE=");
    sep_mbx_puthex(err);
    sep_mbx_putc('\n');
    return 1;
}

static int expect_word(const char *chk, uint32_t addr, uint32_t got, uint32_t exp) {
    if (got == exp) {
        return 0;
    }
    sep_mbx_puts("FAIL: ");
    sep_mbx_puts(chk);
    sep_mbx_puts(" value at ");
    sep_mbx_puthex(addr);
    sep_mbx_puts(" got ");
    sep_mbx_puthex(got);
    sep_mbx_puts(" exp ");
    sep_mbx_puthex(exp);
    sep_mbx_putc('\n');
    return 1;
}

// Words [0] and [NWORDS + 1] keep the pattern; [1..NWORDS] read 0.
static int expect_cleared_words(const char *chk, uint32_t base, const volatile uint32_t *w) {
    int e = 0;
    for (uint32_t i = 0; i < NWORDS + 2u; i++) {
        uint32_t exp = (i == 0 || i == NWORDS + 1u) ? pattern(i) : 0u;
        e += expect_word(chk, base + 4u * i, w[i], exp);
    }
    return e;
}

static int chk_zero_sram(void) {
    int e = 0;
    volatile uint32_t *w = (volatile uint32_t *)SRAM_WORDS_BUF;
    for (uint32_t i = 0; i < NWORDS + 2u; i++) {
        w[i] = pattern(i);
    }
    __asm__ volatile("fence" ::: "memory");
    uint32_t st = zero_fill(SRAM_WORDS_BUF + 4u, NWORDS * 4u, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-SRAM", "4-byte-wide fill", st);
    __asm__ volatile("fence" ::: "memory");
    e += expect_cleared_words("CHK-ZERO-SRAM", SRAM_WORDS_BUF, w);

    volatile uint8_t *b = (volatile uint8_t *)SRAM_BYTES_BUF;
    volatile uint32_t *bw = (volatile uint32_t *)SRAM_BYTES_BUF;
    for (uint32_t i = 0; i < 4u; i++) {
        bw[i] = pattern(i);
    }
    __asm__ volatile("fence" ::: "memory");
    st = zero_fill(SRAM_BYTES_BUF + BYTE_FILL_OFFSET, BYTE_FILL_LEN, SEP_DMA_WIDTH_1B);
    e += expect_clean("CHK-ZERO-SRAM", "1-byte-wide fill", st);
    __asm__ volatile("fence" ::: "memory");
    for (uint32_t i = 0; i < 16u; i++) {
        uint32_t exp = (pattern(i / 4u) >> (8u * (i % 4u))) & 0xFFu;
        if (i >= BYTE_FILL_OFFSET && i < BYTE_FILL_OFFSET + BYTE_FILL_LEN) {
            exp = 0u;
        }
        e += expect_word("CHK-ZERO-SRAM", SRAM_BYTES_BUF + i, b[i], exp);
    }
    if (e == 0) {
        sep_mbx_puts("PASS: CHK-ZERO-SRAM words and bytes cleared, neighbours kept\n");
    }
    return e;
}

static int chk_zero_dccm(void) {
    int e = 0;
    const uint32_t base = (uint32_t)(uintptr_t)dccm_buf;
    for (uint32_t i = 0; i < NWORDS + 2u; i++) {
        dccm_buf[i] = pattern(i);
    }
    __asm__ volatile("fence" ::: "memory");
    uint32_t st = zero_fill(base + 4u, NWORDS * 4u, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-DCCM", "4-byte-wide fill", st);
    __asm__ volatile("fence" ::: "memory");
    e += expect_cleared_words("CHK-ZERO-DCCM", base, dccm_buf);
    if (e == 0) {
        sep_mbx_puts("PASS: CHK-ZERO-DCCM words cleared at ");
        sep_mbx_puthex(base + 4u);
        sep_mbx_puts(", neighbours kept\n");
    }
    return e;
}

static int chk_zero_iccm(void) {
    int e = 0;
    const uint32_t nbytes = (NWORDS + 2u) * 4u;
    volatile uint32_t *src = (volatile uint32_t *)SRAM_PATTERN_BUF;
    volatile uint32_t *ret = (volatile uint32_t *)SRAM_RET_BUF;
    for (uint32_t i = 0; i < NWORDS + 2u; i++) {
        src[i] = pattern(i);
        ret[i] = SENTINEL;
    }
    __asm__ volatile("fence" ::: "memory");
    uint32_t st =
        dma_run(SEP_DMA_OPCODE_COPY, SRAM_PATTERN_BUF, ICCM_ZERO_BASE, nbytes, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-ICCM", "pattern copy to ICCM", st);
    st = zero_fill(ICCM_ZERO_BASE + 4u, NWORDS * 4u, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-ICCM", "4-byte-wide fill", st);
    st = dma_run(SEP_DMA_OPCODE_COPY, ICCM_ZERO_BASE, SRAM_RET_BUF, nbytes, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-ICCM", "copy back from ICCM", st);
    __asm__ volatile("fence" ::: "memory");
    e += expect_cleared_words("CHK-ZERO-ICCM", ICCM_ZERO_BASE, ret);
    if (e == 0) {
        sep_mbx_puts("PASS: CHK-ZERO-ICCM words cleared at ");
        sep_mbx_puthex(ICCM_ZERO_BASE + 4u);
        sep_mbx_puts(", neighbours kept\n");
    }
    return e;
}

static int chk_zero_tcm_narrow(void) {
    int e = 0;
    const uint32_t status_addr = SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_BASE_ADDR;
    const uint32_t clear_addr = SEP_TOP_SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_BASE_ADDR;
    const uint32_t host_bit = SEP_CPU_CTRL__DMA_BUS_ERR_STATUS__HOST_PATH_ERR_bm;

    uint32_t bus = rd(status_addr);
    if (bus != 0) {
        sep_mbx_puts("FAIL: CHK-ZERO-TCM-NARROW DMA_BUS_ERR_STATUS=");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" at baseline, expected 0\n");
        return 1;
    }
    uint32_t st = zero_fill(ICCM_ZERO_BASE, 8u, SEP_DMA_WIDTH_2B);
    uint32_t err = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    bus = rd(status_addr);
    if (!(st & SECURE_DMA__STATUS__ERROR_bm) || err != SECURE_DMA__ERROR_CODE__BUS_ERROR_bm ||
        bus != host_bit) {
        sep_mbx_puts("FAIL: CHK-ZERO-TCM-NARROW STATUS=");
        sep_mbx_puthex(st);
        sep_mbx_puts(" ERROR_CODE=");
        sep_mbx_puthex(err);
        sep_mbx_puts(" DMA_BUS_ERR_STATUS=");
        sep_mbx_puthex(bus);
        sep_mbx_puts(", expected ERROR, BUS_ERROR alone and exclusive host_path_err\n");
        e++;
    }
    wr(clear_addr, SEP_CPU_CTRL__DMA_BUS_ERR_CLEAR__CLR_bm);
    wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, STATUS_RW1C);
    bus = rd(status_addr);
    st = rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    err = rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if (bus != 0 || (st & SECURE_DMA__STATUS__ERROR_bm) || err != 0) {
        sep_mbx_puts("FAIL: CHK-ZERO-TCM-NARROW after CLEAR DMA_BUS_ERR_STATUS=");
        sep_mbx_puthex(bus);
        sep_mbx_puts(" STATUS=");
        sep_mbx_puthex(st);
        sep_mbx_puts(" ERROR_CODE=");
        sep_mbx_puthex(err);
        sep_mbx_puts(", expected 0, ERROR clear and 0\n");
        e++;
    }
    st = zero_fill(ICCM_ZERO_BASE, 8u, SEP_DMA_WIDTH_4B);
    e += expect_clean("CHK-ZERO-TCM-NARROW", "4-byte-wide recovery fill", st);
    if (e == 0) {
        sep_mbx_puts("PASS: CHK-ZERO-TCM-NARROW 2-byte-wide ICCM fill rejected, errors cleared before GO, recovery clean\n");
    }
    return e;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the console window
    sep_mbx_puts("SEP DMA zero fill test\n");

    wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    errors += chk_zero_sram();
    errors += chk_zero_dccm();
    errors += chk_zero_iccm();
    errors += chk_zero_tcm_narrow();

    sep_mbx_puts(errors ? "DMA zero fill test FAILED\n" : "DMA zero fill test PASSED\n");
    return errors;
}
