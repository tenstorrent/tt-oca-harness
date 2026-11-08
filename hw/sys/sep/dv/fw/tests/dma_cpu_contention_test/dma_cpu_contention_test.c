// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure DMA vs CPU LSU contention test, in two legs.
//
// SRAM leg: the CPU starts a long SRAM-to-SRAM DMA copy, then immediately runs
// its own store loop into a disjoint SRAM region, so both masters arbitrate at
// the SRAM target at once. The firmware alone produces the contention; the
// testbench injects nothing.
//
// The DMA copy is 8 times larger than the CPU loop, so the DMA is still busy
// when the loop finishes; that mid-flight status sample proves the two streams
// overlapped. The sizes stay small enough for the Verilator timeout.
//
// SRAM leg checks (main() returns the error count of both legs; startup/crt0.s
// turns it into the PASS/FAIL magic on the mailbox):
//   * overlap: the mid-flight status shows the DMA busy and not done;
//   * the DMA reaches done with no error status and a zero error code;
//   * the done status still reads set after the poll and clears on
//     write-1-to-clear in the polled path;
//   * every copied destination word equals the source pattern;
//   * every CPU-written word equals the CPU pattern;
//   * together these show neither master starved: a starved DMA never reaches
//     done, and a starved CPU stream fails its integrity check.
//
// DCCM leg: the DMA copies an SRAM block into one DCCM array through the core
// DMA slave port while the CPU stores to a second DCCM array, pass after pass,
// until the DMA status shows done or error (bounded). Each pass samples the DMA
// status before its stores and reads its 64 words back after them. The
// firmware logs the DMA status, the error code, the readback mismatch total,
// the number of passes that began with the DMA busy and the pass count, then
// dumps both DCCM arrays; the host grades every word, the mismatch total and
// the DMA status.
//
// Polled, with no interrupts. The DMA registers are clocked on access, so the
// test does not program the DMA clock gate; it inherits the side-effect region
// marking from startup.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"

#define DMA_SRC_ADDR SEP_TOP_SEP_SRAM_BASE_ADDR
#define DMA_DST_ADDR (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x4000u)
#define CONT_ADDR (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x8000u)

#define DMA_BYTES 0x800u // 2 KiB DMA copy (>> CPU loop)
#define DMA_WORDS (DMA_BYTES / 4)
#define CONT_WORDS 64u // 256 B CPU store loop (8:1 vs DMA)

#define SRC_SEED 0xC0DE0000u
#define CPU_SEED 0x5A5A0000u

#define DMA_WAIT_ITERS 4000000 // bounded poll for DONE/ERROR

#define DCCM_SRC_ADDR (SEP_TOP_SEP_SRAM_BASE_ADDR + 0xC000u)
#define DCCM_DMA_BYTES 0x400u // 1 KiB SRAM->DCCM copy
#define DCCM_DMA_WORDS (DCCM_DMA_BYTES / 4)
#define DCCM_CPU_WORDS 64u    // words the CPU stores per pass
#define DCCM_MAX_PASSES 4096u // bound on CPU passes while the DMA runs

#define DCCM_SRC_SEED 0xD0CC0000u
#define DCCM_CPU_SEED 0x3C000000u // pass p, word i: DCCM_CPU_SEED + (p << 16) + i

#define DUMP_WORDS_PER_LINE 8u

// Both arrays sit in .bss, which the tcm link mode places in DCCM below the stack.
static volatile uint32_t dccm_dst[DCCM_DMA_WORDS];
static volatile uint32_t dccm_cont[DCCM_CPU_WORDS];

static void dump_words(const char *tag, const volatile uint32_t *w, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        if (i % DUMP_WORDS_PER_LINE == 0u) {
            sep_mbx_puts(tag);
        }
        sep_mbx_putc(' ');
        sep_mbx_puthex(w[i]);
        if (i % DUMP_WORDS_PER_LINE == DUMP_WORDS_PER_LINE - 1u || i == n - 1u) {
            sep_mbx_putc('\n');
        }
    }
}

// DCCM leg. Returns the firmware error count of the DMA status; the host grades
// the dumped data words.
static int dccm_leg(void) {
    int errors = 0;
    volatile uint32_t *src = (volatile uint32_t *)DCCM_SRC_ADDR;

    for (uint32_t i = 0; i < DCCM_DMA_WORDS; i++) {
        src[i] = DCCM_SRC_SEED + i;
        dccm_dst[i] = 0u;
    }
    for (uint32_t i = 0; i < DCCM_CPU_WORDS; i++) {
        dccm_cont[i] = 0u;
    }
    __asm__ volatile("fence" ::: "memory");
    sep_mbx_puts("STEP DCCM leg: source seeded; DCCM destination and CPU region cleared\n");

    // Start the SRAM->DCCM copy, then store to the CPU array until the DMA
    // reports done or error. Each pass writes a pass-unique pattern, reads it
    // back and counts the words that differ.
    sep_dma_copy_start(DCCM_SRC_ADDR, (uint32_t)(uintptr_t)dccm_dst, DCCM_DMA_BYTES);
    uint32_t passes = 0;
    uint32_t busy_passes = 0;
    uint32_t mismatches = 0;
    uint32_t st = 0;
    do {
        if (sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR) & SECURE_DMA__STATUS__BUSY_bm) {
            busy_passes++;
        }
        for (uint32_t i = 0; i < DCCM_CPU_WORDS; i++) {
            dccm_cont[i] = DCCM_CPU_SEED + (passes << 16) + i;
        }
        __asm__ volatile("fence" ::: "memory");
        for (uint32_t i = 0; i < DCCM_CPU_WORDS; i++) {
            if (dccm_cont[i] != DCCM_CPU_SEED + (passes << 16) + i) {
                mismatches++;
            }
        }
        passes++;
        st = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) &&
             passes < DCCM_MAX_PASSES);
    __asm__ volatile("fence" ::: "memory");

    int timeout = DMA_WAIT_ITERS;
    while (!(st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) && timeout-- > 0) {
        st = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    }
    uint32_t err_code = sep_dma_rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    if ((st & SECURE_DMA__STATUS__ERROR_bm) || !(st & SECURE_DMA__STATUS__DONE_bm) ||
        err_code != 0u) {
        errors++;
    }

    sep_mbx_puts("DCCM-LEG STATUS=");
    sep_mbx_puthex(st);
    sep_mbx_puts(" ERROR_CODE=");
    sep_mbx_puthex(err_code);
    sep_mbx_puts(" mismatches=");
    sep_mbx_puthex(mismatches);
    sep_mbx_puts(" busy_passes=");
    sep_mbx_puthex(busy_passes);
    sep_mbx_puts(" passes=");
    sep_mbx_puthex(passes);
    sep_mbx_puts(" src_seed=");
    sep_mbx_puthex(DCCM_SRC_SEED);
    sep_mbx_puts(" cpu_seed=");
    sep_mbx_puthex(DCCM_CPU_SEED);
    sep_mbx_puts(" dma_words=");
    sep_mbx_puthex(DCCM_DMA_WORDS);
    sep_mbx_puts(" cpu_words=");
    sep_mbx_puthex(DCCM_CPU_WORDS);
    sep_mbx_putc('\n');
    dump_words("DCCM-DST", dccm_dst, DCCM_DMA_WORDS);
    dump_words("DCCM-CPU", dccm_cont, DCCM_CPU_WORDS);
    return errors;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the mailbox window
    sep_mbx_puts("SEP DMA/CPU contention test\n");
    sep_mbx_puts("STEP side-effect region marking inherited from startup\n");

    volatile uint32_t *src = (volatile uint32_t *)DMA_SRC_ADDR;
    volatile uint32_t *dst = (volatile uint32_t *)DMA_DST_ADDR;
    volatile uint32_t *cont = (volatile uint32_t *)CONT_ADDR;

    // Stage the source pattern; clear the DMA destination and the CPU region.
    for (uint32_t i = 0; i < DMA_WORDS; i++) {
        src[i] = SRC_SEED + i;
        dst[i] = 0u;
    }
    for (uint32_t i = 0; i < CONT_WORDS; i++) {
        cont[i] = 0u;
    }
    __asm__ volatile("fence" ::: "memory");
    sep_mbx_puts("STEP source seeded; DMA destination and CPU region cleared\n");

    // Kick off the long SRAM->SRAM copy (non-blocking), then immediately run the
    // CPU store loop into the disjoint region -- both masters now hit the SRAM.
    sep_dma_copy_start(DMA_SRC_ADDR, DMA_DST_ADDR, DMA_BYTES);
    sep_mbx_puts("STEP DMA copy started (non-blocking)\n");
    sep_mbx_puts("STEP CPU store loop entered\n");
    for (uint32_t i = 0; i < CONT_WORDS; i++) {
        cont[i] = CPU_SEED + i;
    }
    __asm__ volatile("fence" ::: "memory");

    // Non-vacuity: the DMA must still be in flight now (BUSY && !DONE).
    uint32_t st_mid = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    if (!((st_mid & SECURE_DMA__STATUS__BUSY_bm) && !(st_mid & SECURE_DMA__STATUS__DONE_bm))) {
        sep_mbx_puts("FAIL: no overlap (DMA not busy mid-CPU-loop) STATUS=");
        sep_mbx_puthex(st_mid);
        sep_mbx_putc('\n');
        errors++;
    }

    // Wait for the DMA to finish; a wedged/starved DMA must FAIL, not hang silent.
    uint32_t st = 0;
    int timeout = DMA_WAIT_ITERS;
    while (timeout-- > 0) {
        st = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) {
            break;
        }
    }
    uint32_t err_code = sep_dma_rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
    uint32_t st_pre_w1c = 0;
    uint32_t st_after_w1c = 0;
    if (st & SECURE_DMA__STATUS__ERROR_bm) {
        sep_mbx_puts("FAIL: DMA error, ERROR_CODE=");
        sep_mbx_puthex(err_code);
        sep_mbx_putc('\n');
        errors++;
    } else if (!(st & SECURE_DMA__STATUS__DONE_bm)) {
        sep_mbx_puts("FAIL: DMA never reached DONE (timeout)\n");
        errors++;
    } else if (err_code != 0u) {
        sep_mbx_puts("FAIL: DMA ERROR_CODE nonzero after DONE ");
        sep_mbx_puthex(err_code);
        sep_mbx_putc('\n');
        errors++;
    } else {
        // STATUS RW1C clear contract (the polled path must prove it too). Done
        // must still read set on a second read after the poll, so a read does
        // not clear it and it does not drop by itself; the clear seen after the
        // write is then the write's.
        st_pre_w1c = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (!(st_pre_w1c & SECURE_DMA__STATUS__DONE_bm)) {
            sep_mbx_puts("FAIL: CHK-RW1C DMA DONE not sticky before W1C, STATUS=");
            sep_mbx_puthex(st_pre_w1c);
            sep_mbx_putc('\n');
            errors++;
        } else {
            uint32_t rw1c = SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm;
            sep_dma_wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, rw1c);
            __asm__ volatile("fence" ::: "memory");
            st_after_w1c = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
            if (st_after_w1c & rw1c) {
                sep_mbx_puts("FAIL: CHK-RW1C DMA STATUS RW1C did not clear, STATUS=");
                sep_mbx_puthex(st_after_w1c);
                sep_mbx_putc('\n');
                errors++;
            }
        }
    }

    // DMA data integrity: every copied word equals the source pattern.
    __asm__ volatile("fence" ::: "memory");
    for (uint32_t i = 0; i < DMA_WORDS; i++) {
        if (dst[i] != (SRC_SEED + i)) {
            sep_mbx_puts("FAIL: DMA dst mismatch\n");
            errors++;
            break;
        }
    }

    // CPU data integrity: the CPU's own stores survived the contention intact.
    for (uint32_t i = 0; i < CONT_WORDS; i++) {
        if (cont[i] != (CPU_SEED + i)) {
            sep_mbx_puts("FAIL: CPU contention-region mismatch\n");
            errors++;
            break;
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: DMA(2KiB) + CPU(256B) SRAM contention; overlap "
                     "STATUS=");
        sep_mbx_puthex(st_mid);
        sep_mbx_puts(", ERROR_CODE=0, DONE+RW1C clear (pre=");
        sep_mbx_puthex(st_pre_w1c);
        sep_mbx_puts(" post=");
        sep_mbx_puthex(st_after_w1c);
        sep_mbx_puts("), dst==src, cont==cpu\n");
    }

    errors += dccm_leg();
    return errors;
}
