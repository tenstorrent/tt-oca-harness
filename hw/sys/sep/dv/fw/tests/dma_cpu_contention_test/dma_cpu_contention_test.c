/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

/* SRAM layout (all inside the OCH-active 64 KB region 0x10000000..0x1000FFFF). */
#define DMA_SRC (OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x00000u)     /* 0x10000000 */
#define DMA_DST (OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x04000u)     /* 0x10004000 */
#define CONT_REGION (OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x08000u) /* 0x10008000 */

#define DMA_BYTES 0x4000u          /* 16 KB DMA copy -> outlasts the CPU loop */
#define DMA_WORDS (DMA_BYTES / 4u) /* 4096 words */
#define CONT_WORDS 256u            /* CPU writes 1 KB (short vs DMA) */

#define SRC_SEED 0xC0DE0000u
#define CPU_SEED 0x5A5A0000u

#define DMA_STATUS_BUSY (1u << 0)
#define DMA_STATUS_DONE (1u << 1)
#define DMA_STATUS_ERROR (1u << 3)

int main(void) {
    sep_outbound_filter_init();

    /* Side-effect region1 (0x10000000..0x1FFFFFFF): SRAM + DMA MMIO uncached so
     * CPU stores stream straight to the bus and DMA STATUS polling is coherent. */
    __asm__ volatile("csrw 0x7c0, %0" : : "r"(0x8));

    printf("=== SS-9.4 FW: secure_dma vs CPU-LSU SRAM target contention ===\n");

    volatile uint32_t *src = (volatile uint32_t *)DMA_SRC;
    volatile uint32_t *dst = (volatile uint32_t *)DMA_DST;
    volatile uint32_t *cont = (volatile uint32_t *)CONT_REGION;

    int errors = 0;

    /* [setup] known source pattern; clear DMA dest and CPU region. */
    for (uint32_t i = 0; i < DMA_WORDS; i++) src[i] = SRC_SEED + i;
    for (uint32_t i = 0; i < DMA_WORDS; i++) dst[i] = 0u;
    for (uint32_t i = 0; i < CONT_WORDS; i++) cont[i] = 0u;
    __asm__ volatile("fence ow, ow" ::: "memory");

    /* [program] secure_dma transfer (full enabled range; SRAM->SRAM; 4B incr). */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x00000000u);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x00000001u);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, DMA_SRC);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0u);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, DMA_DST);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0u);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
              0x77u); /* SRC/DST ASID = OT internal */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2u); /* 4 bytes */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, 0x1u);     /* increment */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, 0x1u);     /* increment */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, DMA_BYTES);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, DMA_BYTES);
    __asm__ volatile("fence ow, ow" ::: "memory");

    /* [GO] non-blocking: OPCODE=COPY, INITIAL_TRANSFER (bit8), GO (bit31). */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, 0x80000100u);

    /* [contend] CPU store loop into CONT region -- concurrent with the DMA. */
    for (uint32_t i = 0; i < CONT_WORDS; i++) cont[i] = CPU_SEED + i;
    __asm__ volatile("fence ow, ow" ::: "memory");

    /* [concurrency] prove the masters overlapped: DMA must still be BUSY now. */
    uint32_t st_mid = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    int overlapped = (st_mid & DMA_STATUS_BUSY) && !(st_mid & DMA_STATUS_DONE);
    if (!overlapped) {
        printf("FAIL [concurrency]: no overlap (status=0x%08x) -- contention not exercised; "
               "increase DMA_BYTES or shrink CONT_WORDS\n",
               st_mid);
        errors++;
    } else {
        printf("PASS [concurrency]: DMA BUSY during CPU writes (status=0x%08x)\n", st_mid);
    }

    /* [wait] DMA DONE or ERROR. */
    uint32_t st = 0u;
    uint32_t guard = 4000000u;
    do {
        st = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    } while (!(st & (DMA_STATUS_DONE | DMA_STATUS_ERROR)) && --guard);

    /* [no_error] */
    if (st & DMA_STATUS_ERROR) {
        printf("FAIL [no_error]: DMA ERROR status=0x%08x ecode=0x%08x\n", st,
               READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
        errors++;
    }
    if (!(st & DMA_STATUS_DONE)) {
        printf("FAIL [no_error]: DMA never reached DONE (status=0x%08x)\n", st);
        errors++;
    }

    /* [dma_integ] DMA copy intact under contention. */
    __asm__ volatile("fence ir, ir" ::: "memory");
    uint32_t dma_bad = 0u;
    for (uint32_t i = 0; i < DMA_WORDS; i++) {
        if (dst[i] != (SRC_SEED + i)) {
            if (dma_bad < 4u) printf("  dma_dst[%u]=0x%08x exp 0x%08x\n", i, dst[i], SRC_SEED + i);
            dma_bad++;
        }
    }
    if (dma_bad) {
        printf("FAIL [dma_integ]: DMA copy corrupted under contention (%u/%u words)\n", dma_bad,
               DMA_WORDS);
        errors++;
    } else {
        printf("PASS [dma_integ]: DMA copy intact (%u words)\n", DMA_WORDS);
    }

    /* [cpu_integ] CPU stores intact under contention. */
    uint32_t cpu_bad = 0u;
    for (uint32_t i = 0; i < CONT_WORDS; i++) {
        if (cont[i] != (CPU_SEED + i)) {
            if (cpu_bad < 4u) printf("  cont[%u]=0x%08x exp 0x%08x\n", i, cont[i], CPU_SEED + i);
            cpu_bad++;
        }
    }
    if (cpu_bad) {
        printf("FAIL [cpu_integ]: CPU writes corrupted under contention (%u/%u words)\n", cpu_bad,
               CONT_WORDS);
        errors++;
    } else {
        printf("PASS [cpu_integ]: CPU writes intact (%u words)\n", CONT_WORDS);
    }

    if (errors == 0) {
        printf("=== SS-9.4 FW PASSED: CPU/DMA SRAM contention, all 4 checks ===\n");
        test_pass(0);
    } else {
        printf("=== SS-9.4 FW FAILED: %d check(s) failed ===\n", errors);
        test_fail(errors);
    }
    return 0;
}
