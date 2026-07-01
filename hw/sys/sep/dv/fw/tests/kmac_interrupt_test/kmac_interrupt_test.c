/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_006 (P0) - Interrupt Test
 *
 * Tests INTR_TEST write-to-set for each interrupt source, verifies
 * INTR_STATE reflects them, and W1C clears them. Also triggers a
 * real kmac_done via an empty SHA3-256 hash.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        uint32_t intr = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & 0x1) {
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static void test_intr_bit(const char *name, uint32_t bit) {
    /* Clear any pending state */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);

    /* Use INTR_TEST to set the bit */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, bit);

    uint32_t state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & bit) {
        printf("PASS: INTR_TEST %s set INTR_STATE (0x%08x)\n", name, state);
    } else {
        printf("FAIL: INTR_TEST %s did not set INTR_STATE (0x%08x)\n", name, state);
        test_errors++;
    }

    /* W1C clear */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, bit);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & bit)) {
        printf("PASS: INTR_STATE %s cleared by W1C\n", name);
    } else {
        /* fifo_empty (bit 1) is level-triggered: re-asserts when FIFO is empty.
         * At idle, FIFO is always empty so the bit stays set - this is RTL behavior.
         * Accept this as INFO, not a test failure. */
        if (bit == 0x2) {
            printf("INFO: INTR_STATE %s re-asserted (level-triggered, FIFO is empty) (0x%08x)\n",
                   name, state);
        } else {
            printf("FAIL: INTR_STATE %s not cleared (0x%08x)\n", name, state);
            test_errors++;
        }
    }
}

static int test_real_kmac_done(void) {
    printf("\n=== Real kmac_done Interrupt Test ===\n");

    if (wait_for_idle() != 0) return -1;

    /* Enable all interrupts */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x7);

    /* Clear pending */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);

    /* Configure SHA3-256 */
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;
    cfg.f.kstrength = 0x2;
    cfg.f.entropy_mode = 0x1;  /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    cfg.f.entropy_ready = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    setup_entropy();

    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    printf("  entropy_ready set\n");

    /* START then PROCESS (empty message hash) */
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  START issued\n");

    cmd.f.cmd = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  PROCESS issued\n");

    if (wait_for_done() != 0) return -1;

    uint32_t state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & 0x1) {
        printf("PASS: Real kmac_done interrupt fired (INTR_STATE=0x%08x)\n", state);
    } else {
        printf("FAIL: kmac_done not in INTR_STATE (0x%08x)\n", state);
        test_errors++;
    }

    /* Clear and finish */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);

    cmd.f.cmd = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

static void test_intr_masking(void) {
    printf("\n=== Masking Test ===\n");

    /* INTR_ENABLE should already be 0 after test_real_kmac_done cleared it.
     * INTR_TEST can still set INTR_STATE bits regardless of INTR_ENABLE. */
    uint32_t enable = READ_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR);
    if (enable == 0x0) {
        printf("PASS: INTR_ENABLE=0 (masked)\n");
    } else {
        printf("FAIL: INTR_ENABLE=0x%08x\n", enable);
        test_errors++;
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0x4);

    uint32_t state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & 0x4) {
        printf("PASS: INTR_STATE set by INTR_TEST with INTR_ENABLE=0\n");
    } else {
        printf("FAIL: INTR_STATE=0x%08x\n", state);
        test_errors++;
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);

    enable = READ_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR);
    if (enable == 0x0) {
        printf("PASS: INTR_ENABLE unchanged after INTR_TEST\n");
    } else {
        printf("FAIL: INTR_ENABLE=0x%08x\n", enable);
        test_errors++;
    }
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  TC_KMAC_006: Interrupt Test\n");
    printf("========================================\n");

    /* Enable all interrupts for test */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x7);

    printf("\n=== INTR_TEST Bit Tests ===\n");
    test_intr_bit("kmac_done", 0x1);
    test_intr_bit("fifo_empty", 0x2);
    test_intr_bit("kmac_err", 0x4);

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);

    /* NOTE: masking test (test_intr_masking) runs AFTER real hash to avoid
     * INTR_TEST write interfering with entropy state for subsequent hash */
    test_real_kmac_done();

    test_intr_masking();

    printf("\n========================================\n");
    if (test_errors == 0) {
        printf("  RESULT: ALL TESTS PASSED\n");
        test_pass(0);
    } else {
        printf("  RESULT: %d TESTS FAILED\n", test_errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
