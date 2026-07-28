// SPDX-License-Identifier: Apache-2.0
//
// SEP Secure-DMA inline SHA-256 firmware test (OSS port of the OCAH
// dma_hash_test). The EL2 CPU programs the Secure DMA to copy a buffer with the
// inline SHA-256 engine, waits for the DMA-done interrupt (WFI + ISR, via the
// VeeR PIC), then self-checks:
//   * DMA STATUS.DONE was observed by the ISR and RW1C-cleared,
//   * DMA ERROR_CODE == 0,
//   * the hardware SHA-256 digest == a software SHA-256 over the same data, and
//   * the copied bytes match the source.
// main() returns the error count; start.S turns 0 -> PASS magic, non-zero ->
// FAIL magic on the 0x8000_0000 mailbox. Edges exercised: E7 (DMA + inline SHA)
// and E10 (DMA-done IRQ -> PIC -> CPU -> ISR).
//
// The transfer is SRAM->DCCM, matching OCAH: the DMA master reaches DCCM through
// the SEP local xbar -> VeeR EL2 dma_axi slave port. The firmware's src==dst data
// check confirms the DMA-written DCCM is visible to the CPU.

#include <stdint.h>
#include <string.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"
#include "sep_pic.h"
#include "sha256.h"

// PIC source = internal-interrupt index + 1 (VeeR source 0 is the tied
// no-interrupt source). intr_dma_done -> sep_internal_interrupts[8] -> source 9;
// intr_dma_error -> [11] -> source 12 (hw/sep/sep.sv interrupt map).
#define EXT_INT_DMA_DONE 9
#define EXT_INT_DMA_ERROR 12

#define TEST_DATA_SIZE 0x100u    // 256 bytes (multiple of 4)
#define DMA_SRC_ADDR 0x10000000u // SEP SRAM base
#define DMA_DST_ADDR 0xC0042000u // DCCM, high enough to clear .data/.bss/.intvec
#define DMA_STATUS_RW1C_MASK \
    (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR | SEP_DMA_STATUS_CHUNK_DONE)

static volatile uint32_t dma_interrupt_fired = 0;
static volatile uint32_t dma_status_before_clear = 0;
static volatile uint32_t dma_status_after_clear = 0;

// DMA done/error ISR: flag the wakeup and clear the DMA status (RW1C) at source.
void __attribute__((interrupt("machine"))) dma_isr(void) {
    dma_status_before_clear = sep_dma_rd(SEP_DMA_STATUS);
    sep_dma_wr(SEP_DMA_STATUS, DMA_STATUS_RW1C_MASK);
    __asm__ volatile("fence" ::: "memory");
    dma_status_after_clear = sep_dma_rd(SEP_DMA_STATUS);
    dma_interrupt_fired = 1;
    __asm__ volatile("fence" ::: "memory");
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the 0x8000_0000 mailbox window
    sep_mbx_puts("SEP DMA SHA-256 test\n");

    // Route the DMA done/error interrupts to the ISR through the VeeR PIC.
    pic_register_handler(EXT_INT_DMA_DONE, dma_isr);
    pic_register_handler(EXT_INT_DMA_ERROR, dma_isr);
    pic_set_gateway(EXT_INT_DMA_DONE, 0, 0); // level-triggered, active-high
    pic_set_gateway(EXT_INT_DMA_ERROR, 0, 0);
    pic_set_priority(EXT_INT_DMA_DONE, 1);
    pic_set_priority(EXT_INT_DMA_ERROR, 1);
    pic_enable_source(EXT_INT_DMA_DONE);
    pic_enable_source(EXT_INT_DMA_ERROR);
    pic_enable_interrupts();

    // Fill the source with a deterministic pattern (LCG; reproducible, and the
    // digest is checked against a software hash of the very same bytes).
    volatile uint32_t *src = (volatile uint32_t *)DMA_SRC_ADDR;
    uint32_t lfsr = 0x1234567u;
    for (uint32_t i = 0; i < TEST_DATA_SIZE / 4; i++) {
        lfsr = lfsr * 1664525u + 1013904223u;
        src[i] = lfsr;
    }

    // Kick off the copy + inline SHA-256 and wait for the DMA-done interrupt.
    dma_interrupt_fired = 0;
    dma_status_before_clear = 0;
    dma_status_after_clear = 0;
    sep_dma_sha256_start(DMA_SRC_ADDR, DMA_DST_ADDR, TEST_DATA_SIZE);

    int timeout = 100000;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (dma_interrupt_fired) {
            break;
        }
    }

    uint32_t err = sep_dma_rd(SEP_DMA_ERROR_CODE);
    if (!dma_interrupt_fired) {
        sep_mbx_puts("FAIL: DMA timeout (no interrupt)\n");
        errors++;
    } else {
        if ((dma_status_before_clear & SEP_DMA_STATUS_DONE) == 0) {
            sep_mbx_puts("FAIL: DMA ISR did not observe STATUS.done\n");
            errors++;
        }
        if (dma_status_before_clear & SEP_DMA_STATUS_ERROR) {
            sep_mbx_puts("FAIL: DMA ISR observed STATUS.error\n");
            errors++;
        }
        if (dma_status_after_clear & DMA_STATUS_RW1C_MASK) {
            sep_mbx_puts("FAIL: DMA STATUS RW1C bits did not clear\n");
            errors++;
        }
        if (err != 0) {
            sep_mbx_puts("FAIL: DMA error\n");
            errors++;
        }
    }

    // Software SHA-256 of the source data (golden reference).
    uint8_t sw_hash[32];
    SHA256_CTX ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, (const BYTE *)src, TEST_DATA_SIZE);
    sha256_final(&ctx, sw_hash);

    // Hardware digest from the DMA (DIGEST_SWAP made it big-endian like the SW).
    uint32_t hw_words[8];
    for (int i = 0; i < 8; i++) {
        hw_words[i] = sep_dma_rd(SEP_DMA_SHA2_DIGEST_0 + i * 4);
    }
    if (memcmp((const void *)hw_words, sw_hash, 32) != 0) {
        sep_mbx_puts("FAIL: SHA-256 digest mismatch\n");
        errors++;
    }

    // The copied bytes must match the source.
    volatile uint32_t *dst = (volatile uint32_t *)DMA_DST_ADDR;
    for (uint32_t i = 0; i < TEST_DATA_SIZE / 4; i++) {
        if (src[i] != dst[i]) {
            sep_mbx_puts("FAIL: copied data mismatch\n");
            errors++;
            break;
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: DMA IRQ RW1C + copy + inline SHA-256 verified\n");
    }
    return errors;
}
