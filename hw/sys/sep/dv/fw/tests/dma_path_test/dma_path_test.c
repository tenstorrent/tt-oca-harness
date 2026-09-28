/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * DMA Path Verification Test
 *
 * Tests DMA paths that the ROM boot flow depends on:
 *   Phase 1: SRAM -> SRAM  (simulates Flash -> SRAM, same DMA engine)
 *   Phase 2: SRAM -> ICCM -> SRAM roundtrip (data path verification)
 *   Phase 3: SRAM -> ICCM, then JUMP to ICCM (IFU fetch / ECC verification)
 *
 * Phase 3 is the critical test: if DMA writes data correctly but doesn't
 * generate proper ECC bits, IFU fetch will fail and CPU will hang.
 * This distinguishes data-path issues from ECC issues.
 *
 * NOTE: This test runs from ICCM (BACKDOOR_TCM). DMA targets are placed
 * at ICCM + 0x20000/0x30000 to avoid overwriting test code.
 *
 * Address map:
 *   SRAM:  0x10000000, 256KB
 *   ICCM:  0xC0000000, 256KB
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define BIT(n) (1u << (n))

#define TEST_SIZE 0x100 /* 256 bytes */
#define TEST_WORDS (TEST_SIZE / 4)

/* SRAM regions */
#define SRAM_SRC (SEP_TOP_SEP_SRAM_BASE_ADDR)           /* 0x10000000 */
#define SRAM_DST1 (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000) /* 0x10001000 */
#define SRAM_DST2 (SEP_TOP_SEP_SRAM_BASE_ADDR + 0x2000) /* 0x10002000 - for ICCM readback */

/* ICCM targets: offset to avoid overwriting test code */
#define ICCM_DST (SEP_TOP_SEP_ICCM_BASE_ADDR + 0x20000)  /* 0xC0020000 - Phase 2 data */
#define ICCM_CODE (SEP_TOP_SEP_ICCM_BASE_ADDR + 0x30000) /* 0xC0030000 - Phase 3 code */

/* Test patterns */
#define PATTERN_SRAM 0xAA550000u
#define PATTERN_ICCM 0xBB660000u

/*
 * Phase 3 machine code: position-independent RISC-V instructions that
 * write the test_pass magic sequence (TEST_MAGIC0 + TEST_MAGIC_PASS)
 * to STDOUT (0x80000000), then halt.
 *
 * Equivalent assembly:
 *   lui   t0, 0x80000          # t0 = 0x80000000 (STDOUT)
 *   lui   t1, 0xA5A56          # \
 *   addi  t1, t1, -1446        # / t1 = 0xA5A55A5A (TEST_MAGIC0)
 *   sw    t1, 0(t0)            # write magic0
 *   fence                      # ensure write completes
 *   lui   t1, 0xCAFEC          # \
 *   addi  t1, t1, -1346        # / t1 = 0xCAFEBABE (TEST_MAGIC_PASS)
 *   sw    t1, 0(t0)            # write pass
 *   wfi                        # halt
 *   j     -4                   # loop back to wfi
 */
static const uint32_t phase3_code[] = {
    0x800002B7, /* lui   t0, 0x80000                                    */
    0xA5A56337, /* lui   t1, 0xA5A56                                    */
    0xA5A30313, /* addi  t1, t1, -1446    ; t1 = 0xA5A55A5A            */
    0x0062A023, /* sw    t1, 0(t0)        ; STDOUT <- TEST_MAGIC0      */
    0x0FF0000F, /* fence                                                */
    0xCAFEC337, /* lui   t1, 0xCAFEC                                    */
    0xABE30313, /* addi  t1, t1, -1346    ; t1 = 0xCAFEBABE            */
    0x0062A023, /* sw    t1, 0(t0)        ; STDOUT <- TEST_MAGIC_PASS  */
    0x10500073, /* wfi                                                  */
    0xFFDFF06F, /* j     -4               ; loop back to wfi           */
};

#define PHASE3_CODE_SIZE sizeof(phase3_code)

/*==========================================================================
 * DMA helper (from sep_dma.c, simplified for test)
 *==========================================================================*/

static void dma_init(void) {
    WRITE_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x00000000u);
    WRITE_REG(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x00000001u);
}

static int dma_copy(uint32_t dst, uint32_t src, uint32_t size) {
    /* Check if destination or source is ICCM - need to disable axi_local_alias_remap */
    int iccm_dest = (dst >= SEP_TOP_SEP_ICCM_BASE_ADDR &&
                     dst < SEP_TOP_SEP_ICCM_BASE_ADDR + SEP_TOP_SEP_ICCM_SIZE);
    int iccm_src = (src >= SEP_TOP_SEP_ICCM_BASE_ADDR &&
                    src < SEP_TOP_SEP_ICCM_BASE_ADDR + SEP_TOP_SEP_ICCM_SIZE);
    uint32_t saved_region_size = 0;

    if (iccm_dest || iccm_src) {
        saved_region_size = READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR);
        printf("  [remap] old SEP_REGION_SIZE=0x%08x\n", saved_region_size);
        WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR, 0u);
        __asm__ volatile("fence ow, ow" ::: "memory");
        printf("  [remap] new SEP_REGION_SIZE=0x%08x\n",
               READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR));
    }

    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0u);
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst);
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0u);
    WRITE_REG(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, 0x77u);
    WRITE_REG(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2u); /* 4 bytes */
    WRITE_REG(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, 0x1u);     /* increment */
    WRITE_REG(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, 0x1u);     /* increment */
    WRITE_REG(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, size);
    WRITE_REG(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, size);

    /* GO */
    WRITE_REG(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, 0x80000100u);

    /* Poll for completion */
    int timeout = 200000;
    while (timeout-- > 0) {
        uint32_t status = READ_REG(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status & BIT(1)) { /* DONE */
            break;
        }
        if (status & BIT(3)) { /* ERROR */
            uint32_t ecode = READ_REG(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
            printf("  DMA ERROR: status=0x%08x error_code=0x%08x\n", status, ecode);
            printf("  src=0x%08x dst=0x%08x len=0x%x\n", src, dst, size);
            if (iccm_dest || iccm_src)
                WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR, saved_region_size);
            return -1;
        }
    }

    if (timeout <= 0) {
        printf("  DMA TIMEOUT: src=0x%08x dst=0x%08x len=0x%x\n", src, dst, size);
        if (iccm_dest || iccm_src)
            WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR, saved_region_size);
        return -2;
    }

    /* Restore remap */
    if (iccm_dest || iccm_src) {
        WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR, saved_region_size);
        printf("  [remap] restored SEP_REGION_SIZE=0x%08x\n",
               READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR));
    }

    return 0;
}

/*==========================================================================
 * Verification helper
 *==========================================================================*/

static int verify_sram(uint32_t addr, uint32_t pattern, int count) {
    volatile uint32_t *p = (volatile uint32_t *)addr;
    int errors = 0;

    for (int i = 0; i < count; i++) {
        uint32_t expected = pattern + i;
        uint32_t actual = p[i];
        if (actual != expected) {
            if (errors < 8) {
                printf("    MISMATCH [%d]: addr=0x%08x expected=0x%08x got=0x%08x\n", i,
                       (uint32_t)(addr + i * 4), expected, actual);
            }
            errors++;
        }
    }
    return errors;
}

/*==========================================================================
 * Main
 *==========================================================================*/

int main(void) {
    sep_outbound_filter_init();

    /* Side-effect region for DMA */
    __asm__ volatile("csrw 0x7c0, %0" : : "r"(0x8));

    int total_errors = 0;

    printf("=== DMA Path Verification Test ===\n\n");

    /* Initialize DMA */
    dma_init();
    printf("DMA initialized\n\n");

    /*======================================================================
     * Phase 1: SRAM -> SRAM (simulates Flash -> SRAM path)
     *======================================================================*/
    printf("--- Phase 1: SRAM -> SRAM ---\n");
    printf("  src=0x%08x dst=0x%08x size=0x%x\n", SRAM_SRC, SRAM_DST1, TEST_SIZE);

    /* Fill source with pattern, clear destination */
    volatile uint32_t *src = (volatile uint32_t *)SRAM_SRC;
    volatile uint32_t *dst1 = (volatile uint32_t *)SRAM_DST1;
    for (int i = 0; i < TEST_WORDS; i++) {
        src[i] = PATTERN_SRAM + i;
        dst1[i] = 0;
    }

    /* DMA copy */
    int ret = dma_copy(SRAM_DST1, SRAM_SRC, TEST_SIZE);
    if (ret != 0) {
        printf("  Phase 1 FAIL: DMA error (%d)\n\n", ret);
        total_errors++;
    } else {
        /* Verify */
        int errs = verify_sram(SRAM_DST1, PATTERN_SRAM, TEST_WORDS);
        if (errs == 0) {
            printf("  Phase 1 PASS: %d words verified OK\n\n", TEST_WORDS);
        } else {
            printf("  Phase 1 FAIL: %d/%d mismatches\n\n", errs, TEST_WORDS);
            total_errors += errs;
        }
    }

    /*======================================================================
     * Phase 2: SRAM -> ICCM (the BL1 handoff path) - data verification
     *======================================================================*/
    printf("--- Phase 2: SRAM -> ICCM ---\n");
    printf("  src=0x%08x dst=0x%08x size=0x%x\n", SRAM_SRC, ICCM_DST, TEST_SIZE);

    /* Fill source with different pattern */
    for (int i = 0; i < TEST_WORDS; i++) {
        src[i] = PATTERN_ICCM + i;
    }

    /* DMA: SRAM -> ICCM */
    ret = dma_copy(ICCM_DST, SRAM_SRC, TEST_SIZE);
    if (ret != 0) {
        printf("  Phase 2a (SRAM->ICCM) FAIL: DMA error (%d)\n\n", ret);
        total_errors++;
    } else {
        printf("  Phase 2a (SRAM->ICCM) DMA completed OK\n");

        /*
         * Phase 2b: verify by DMA-ing ICCM back to SRAM
         * (CPU LSU cannot read ICCM on VeeR EL2)
         */
        printf("--- Phase 2b: ICCM -> SRAM (readback verify) ---\n");
        printf("  src=0x%08x dst=0x%08x size=0x%x\n", ICCM_DST, SRAM_DST2, TEST_SIZE);

        /* Clear readback destination */
        volatile uint32_t *dst2 = (volatile uint32_t *)SRAM_DST2;
        for (int i = 0; i < TEST_WORDS; i++) {
            dst2[i] = 0;
        }

        ret = dma_copy(SRAM_DST2, ICCM_DST, TEST_SIZE);
        if (ret != 0) {
            printf("  Phase 2b (ICCM->SRAM) FAIL: DMA error (%d)\n\n", ret);
            total_errors++;
        } else {
            int errs = verify_sram(SRAM_DST2, PATTERN_ICCM, TEST_WORDS);
            if (errs == 0) {
                printf("  Phase 2 PASS: SRAM->ICCM->SRAM %d words verified OK\n\n", TEST_WORDS);
            } else {
                printf("  Phase 2 FAIL: %d/%d mismatches after ICCM roundtrip\n\n", errs,
                       TEST_WORDS);
                total_errors += errs;
            }
        }
    }

    /*======================================================================
     * Early exit if Phase 1 or 2 failed
     *======================================================================*/
    if (total_errors != 0) {
        printf("=== Skipping Phase 3 due to earlier failures ===\n");
        printf("FAILED: %d total errors\n", total_errors);
        test_fail(total_errors);
        while (1) {
            __asm__("wfi");
        }
    }

    /*======================================================================
     * Phase 3: SRAM -> ICCM, then EXECUTE from ICCM
     *
     * This is the definitive ECC test. DMA writes executable code to ICCM,
     * then we jump to it. If DMA doesn't produce correct ECC, the IFU
     * fetch will fail and CPU will hang (test timeout = FAIL).
     *
     * The code at ICCM_CODE writes test_pass magic to STDOUT.
     *======================================================================*/
    printf("--- Phase 3: SRAM -> ICCM + EXECUTE (ECC test) ---\n");
    printf("  Copying %u bytes of code to ICCM @ 0x%08x\n", (unsigned)PHASE3_CODE_SIZE, ICCM_CODE);

    /* Copy phase3_code into SRAM source area first */
    volatile uint32_t *code_src = (volatile uint32_t *)SRAM_SRC;
    for (unsigned i = 0; i < PHASE3_CODE_SIZE / 4; i++) {
        code_src[i] = phase3_code[i];
    }

    /* DMA: SRAM -> ICCM (code region) */
    ret = dma_copy(ICCM_CODE, SRAM_SRC, PHASE3_CODE_SIZE);
    if (ret != 0) {
        printf("  Phase 3 FAIL: DMA error (%d)\n", ret);
        test_fail(ret);
        while (1) {
            __asm__("wfi");
        }
    }

    printf("  DMA completed. Jumping to ICCM code @ 0x%08x ...\n", ICCM_CODE);
    printf("  (If CPU hangs here, DMA wrote bad ECC to ICCM)\n");

    /* fence.i to synchronize instruction and data streams */
    __asm__ volatile("fence.i" ::: "memory");

    /* Jump to DMA'd code in ICCM - this should signal test_pass */
    void (*iccm_func)(void) = (void (*)(void))(uintptr_t)ICCM_CODE;
    iccm_func();

    /* Should never reach here - ICCM code does test_pass + wfi */
    printf("  ERROR: returned from ICCM code (should not happen)\n");
    test_fail(0xFF);
    while (1) {
        __asm__("wfi");
    }
}
