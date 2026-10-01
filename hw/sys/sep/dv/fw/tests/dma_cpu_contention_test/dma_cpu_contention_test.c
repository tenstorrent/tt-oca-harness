// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Secure-DMA vs CPU-LSU SRAM contention firmware test (OSS port of the reference suite
// dma_cpu_contention_test). The Secure-DMA master and the
// CPU-LSU master concurrently drive the SEP-local AXI xbar to the shared SRAM
// slave (0x1000_0000). The EL2 CPU kicks off a long SRAM->SRAM DMA copy, then
// immediately runs its own store loop into a DISJOINT SRAM region while the DMA
// is still in flight, so both masters arbitrate at the SRAM target at once.
// Everything is internal to bare `sep` -- the firmware itself produces the
// contention, no testbench injection.
//
// The DMA copy is much larger than the CPU loop (2 KiB vs 256 B,
// 8:1) so the DMA is provably still busy when the CPU loop finishes -- that
// mid-flight STATUS read is the non-vacuity proof that the two streams really
// overlapped. Sizes stay small enough for the Verilator timeout; the 8:1
// imbalance is what makes the mid-flight BUSY && !DONE sample a real overlap.
//
// Checks (every failure increments errors; main() returns it and start.S turns
// 0 -> PASS magic / non-zero -> FAIL magic on the 0x8000_0000 mailbox):
//   * overlap (non-vacuity): mid-flight STATUS shows BUSY==1 && DONE==0;
//   * the DMA reaches DONE with ERROR==0 and ERROR_CODE==0;
//   * STATUS RW1C clear: W1C the DONE/CHUNK_DONE bits and read back 0 (AGENTS.md
//     the contract holds for polled status, not just ISR paths; reference suite does
//     not clear, so this is a strengthening);
//   * DMA data integrity: every copied dst word == the source pattern;
//   * CPU data integrity: every CPU-written word == the CPU pattern (proves the
//     CPU's own stores were not corrupted/dropped under contention);
//   * no master starvation is proven jointly by the above -- a starved DMA never
//     reaches DONE (timeout FAIL) and a starved/corrupted CPU stream fails the
//     CPU-integrity check.
//
// Polled, interrupt-free: no PIC/ISR. DMA CSRs are dynamically clocked on
// access; this test does not write CLOCK_GATE_CTRL. Side-effect region marking
// is inherited from startup; this test does not write MRAC.

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

    sep_outbound_filter_init(); // open the 0x8000_0000 mailbox window
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
        // STATUS RW1C clear contract (the polled path must prove it too).
        uint32_t rw1c = SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm;
        sep_dma_wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, rw1c);
        __asm__ volatile("fence" ::: "memory");
        uint32_t st_after = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (st_after & rw1c) {
            sep_mbx_puts("FAIL: DMA STATUS RW1C did not clear, STATUS=");
            sep_mbx_puthex(st_after);
            sep_mbx_putc('\n');
            errors++;
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
        sep_mbx_puts(", ERROR_CODE=0, DONE+RW1C clear, dst==src, cont==cpu\n");
    }
    return errors;
}
