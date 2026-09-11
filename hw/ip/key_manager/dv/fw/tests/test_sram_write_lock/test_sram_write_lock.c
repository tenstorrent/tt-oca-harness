/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_sram_write_lock.c
 * @brief SRAM write-lock test, one subtest per lockable region
 *
 * Verifies SRAM write-locking:
 * - For each region: lock region, attempt write, verify write dropped,
 *   verify SRAM_WRITE_LOCK_VIOLATION status bit, verify IRQ_STATUS.sram_write_lock_err
 * - Tests write-1-only lock (only 1s set)
 * - Tests sticky W1C violation and IRQ status
 *
 * Skip only the regions that would corrupt or hang the running firmware:
 * - Any region that overlaps linker-placed .data or .bss.
 * - The region containing the active C stack frame.
 * - Region 15 (0xBC00-0xBFFF): locking it hangs the running firmware.
 *
 * Run with:
 *   make run_fw FW_TEST=test_sram_write_lock
 */

#include "test_common.h"
#include "rom_defs.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define NUM_SRAM_REGIONS (ROM_KM_SRAM_SIZE / SRAM_LOCK_REGION_BYTES)
#define BYTES_PER_REGION SRAM_LOCK_REGION_BYTES
#define SRAM_REGION_BASE(r) (SRAM_BASE + (uint32_t)(r)*BYTES_PER_REGION)

/* Offset within each region for the test write. */
#define OFFSET_IN_REGION 0x100u

#define REGION_SKIP_HANG 15u /* 0xBC00-0xBFFF - causes hang when tested */
#define REGION_FIRST 0u
#define REGION_LAST (NUM_SRAM_REGIONS - 1u)

/* Register access for SRAM lock and violation */
#define SRAM_LOCK_REG (*(volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR)
#define SRAM_VIOLATION_REG \
    (*(volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR)

extern char DATA_START[];
extern char DATA_END[];
extern char BSS_START[];
extern char BSS_END[];

static void clear_violation_and_irq_status(void) {
    SRAM_VIOLATION_REG = 0xFFFFFFFFu; /* W1C: clear all violation bits */
    km_csr__irq_status_reg_t clear_val = {0};
    clear_val.f.sram_write_lock_err = 1;
    KMCSR_IRQ_STATUS_REG.w = clear_val.w; /* W1C: clear sram_write_lock_err */

    uint32_t v = SRAM_VIOLATION_REG;
    if (v != 0u) {
        TEST_FAIL("SRAM_WRITE_LOCK_VIOLATION not cleared after W1C (read 0x%08X)", v);
    }
    if (KMCSR_IRQ_STATUS_REG.f.sram_write_lock_err) {
        TEST_FAIL("IRQ_STATUS.sram_write_lock_err not cleared after W1C (read 0x%08X)",
                  KMCSR_IRQ_STATUS_REG.w);
    }
}

static inline void lock_region(uint32_t region) {
    SRAM_LOCK_REG = (1u << region); /* Write-1-only: set bit for this region */
}

static inline uint32_t read_irq_status(void) {
    return KMCSR_IRQ_STATUS_REG.w;
}

static uint32_t region_for_addr(uintptr_t addr) {
    return (uint32_t)((addr - (uintptr_t)SRAM_BASE) / BYTES_PER_REGION);
}

static int region_overlaps_range(uint32_t region, uintptr_t start, uintptr_t end) {
    uintptr_t region_start = (uintptr_t)SRAM_REGION_BASE(region);
    uintptr_t region_end = region_start + BYTES_PER_REGION;

    return (start < region_end) && (end > region_start);
}

static int should_skip_region(uint32_t region, uintptr_t active_stack_addr) {
    if (region == REGION_SKIP_HANG) {
        return 1;
    }

    if (region_overlaps_range(region, (uintptr_t)DATA_START, (uintptr_t)DATA_END)) {
        return 1;
    }

    if (region_overlaps_range(region, (uintptr_t)BSS_START, (uintptr_t)BSS_END)) {
        return 1;
    }

    return region == region_for_addr(active_stack_addr);
}

int main(void) {
    volatile uint32_t stack_marker = 0u;
    uint32_t stack_region = region_for_addr((uintptr_t)&stack_marker);

    TEST_INIT();

    if (!tb_set_timeout(200000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("SRAM Write-Lock Test (regions %u-%u; skip data/bss overlaps, hang region %u, stack "
           "region %u)\n",
           (unsigned)REGION_FIRST, (unsigned)REGION_LAST, (unsigned)REGION_SKIP_HANG,
           (unsigned)stack_region);
    printf("============================================================================\n\n");

    /* Disable SRAM write-lock IRQ for most of test - we check status only */
    KMCSR_IRQ_ENABLE_REG.w = 0;

    for (uint32_t region = REGION_FIRST; region <= REGION_LAST; region++) {
        if (should_skip_region(region, (uintptr_t)&stack_marker)) {
            continue;
        }
        volatile uint32_t *addr =
            (volatile uint32_t *)(SRAM_REGION_BASE(region) + OFFSET_IN_REGION);
        const uint32_t pattern_before = 0xDEAD0000u + region;
        const uint32_t pattern_after = 0xCAFE0000u + region;

        TEST_SUBTEST_START("Region lock drop write status");
        TEST_LOG("  Testing region %u", (unsigned)region);

        clear_violation_and_irq_status();

        /* Write initial pattern (region not locked yet) */
        *addr = pattern_before;
        __asm__ volatile("fence" ::: "memory");
        uint32_t readback = *addr;
        if (readback != pattern_before) {
            TEST_FAIL("Region %u: initial write failed (read 0x%08X)", (unsigned)region, readback);
        }

        /* Lock this region (write-1-only) */
        lock_region(region);
        __asm__ volatile("fence" ::: "memory");

        /* Verify lock register was written (read back SRAM_LOCK; catch RTL/visibility issues) */
        {
            uint32_t lock_val = SRAM_LOCK_REG;
            if ((lock_val & (1u << region)) == 0) {
                TEST_FAIL("Region %u: SRAM_LOCK bit not set after lock_region (read 0x%08X)",
                          (unsigned)region, lock_val);
            }
        }

        /* Write-1-only: writing 0 must not clear this region's lock bit */
        SRAM_LOCK_REG = 0u;
        __asm__ volatile("fence" ::: "memory");
        if ((SRAM_LOCK_REG & (1u << region)) == 0) {
            TEST_FAIL("Region %u: SRAM_LOCK bit %u cleared by write 0 (read 0x%08X)",
                      (unsigned)region, (unsigned)region, SRAM_LOCK_REG);
        }

        /* Attempt write to locked region - should be dropped */
        *addr = pattern_after;
        __asm__ volatile("fence" ::: "memory");

        /* Read back: must still see pattern_before (write was dropped) */
        readback = *addr;
        if (readback != pattern_before) {
            TEST_FAIL("Region %u: write was not dropped (read 0x%08X, expected 0x%08X)",
                      (unsigned)region, readback, pattern_before);
        }

        /* Violation status: bit[region] must be set */
        uint32_t violation = SRAM_VIOLATION_REG;
        if (!(violation & (1u << region))) {
            TEST_FAIL("Region %u: SRAM_WRITE_LOCK_VIOLATION bit not set (reg=0x%08X)",
                      (unsigned)region, violation);
        }

        /* W1C: clear this region's violation bit and verify it is cleared */
        SRAM_VIOLATION_REG = (1u << region);
        violation = SRAM_VIOLATION_REG;
        if (violation & (1u << region)) {
            TEST_FAIL("Region %u: SRAM_WRITE_LOCK_VIOLATION bit not cleared by W1C (reg=0x%08X)",
                      (unsigned)region, violation);
        }

        /* IRQ status: sram_write_lock_err must be set */
        uint32_t irq_status = read_irq_status();
        km_csr__irq_status_reg_t status_reg = {.w = irq_status};
        if (!status_reg.f.sram_write_lock_err) {
            TEST_FAIL("Region %u: IRQ_STATUS.sram_write_lock_err not set (reg=0x%08X)",
                      (unsigned)region, irq_status);
        }

        TEST_SUBTEST_PASS();
    }

    printf("\nAll SRAM write-lock tests passed.\n");
    TEST_PASS();
    return 0;
}
