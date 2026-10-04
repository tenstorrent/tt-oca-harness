// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure DMA vs CPU LSU SRAM contention test. The CPU starts a long
// SRAM-to-SRAM DMA copy, then immediately runs its own store loop into a
// disjoint SRAM region, so both masters arbitrate at the SRAM target at once.
// The firmware alone produces the contention; the testbench injects nothing.
//
// The DMA copy is 8 times larger than the CPU loop, so the DMA is still busy
// when the loop finishes; that mid-flight status sample proves the two streams
// overlapped. The sizes stay small enough for the Verilator timeout.
//
// Checks (main() returns the error count; startup/crt0.s turns it into the
// PASS/FAIL magic on the mailbox):
//   * overlap: the mid-flight status shows the DMA busy and not done;
//   * the DMA reaches done with no error status and a zero error code;
//   * the done status still reads set after the poll and clears on
//     write-1-to-clear in the polled path;
//   * every copied destination word equals the source pattern;
//   * every CPU-written word equals the CPU pattern;
//   * together these show neither master starved: a starved DMA never reaches
//     done, and a starved CPU stream fails its integrity check.
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
    return errors;
}
