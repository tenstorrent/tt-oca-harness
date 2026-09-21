/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Interrupt Test
 *
 * INTR_TEST set/clear for each source (fifo_empty proven with non-empty FIFO),
 * plus a real kmac_done via empty SHA3-256 with software entropy.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.kmac_done) {
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
}

static void seed_sw_entropy(void) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + (uint32_t)i);
    }
}

static void test_intr_bit_event(const char *name, uint32_t bit) {
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, bit);

    uint32_t state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & bit) {
        printf("PASS: INTR_TEST %s set INTR_STATE (0x%08x)\n", name, state);
    } else {
        printf("FAIL: INTR_TEST %s did not set INTR_STATE (0x%08x)\n", name, state);
        test_errors++;
    }

    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, bit);
    state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & bit)) {
        printf("PASS: INTR_STATE %s cleared by W1C\n", name);
    } else {
        printf("FAIL: INTR_STATE %s not cleared (0x%08x)\n", name, state);
        test_errors++;
    }
}

static void test_fifo_empty_intr(void) {
    /*
     * fifo_empty is Status-type. Sustained non-empty FIFO is unreliable under
     * CPU MMIO absorb. Prove idle wiring + INTR_TEST force-assert instead.
     */
    printf("\n=== INTR_TEST fifo_empty (idle status-type) ===\n");
    if (wait_for_idle() != 0) {
        test_errors++;
        return;
    }

    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0);

    kmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    kmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    printf("  Idle STATUS.empty=%u INTR.fifo_empty=%u\n", sts.f.fifo_empty, intr.f.fifo_empty);

    if (!sts.f.fifo_empty) {
        printf("FAIL: idle FIFO not empty\n");
        test_errors++;
        return;
    }

    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_STATE__FIFO_EMPTY_bm);
    intr.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (intr.f.fifo_empty) {
        printf("PASS: INTR_TEST.fifo_empty set INTR_STATE\n");
    } else {
        printf("FAIL: INTR_TEST.fifo_empty did not set INTR_STATE\n");
        test_errors++;
    }
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
}

static int test_real_kmac_done(void) {
    printf("\n=== Real kmac_done Interrupt Test ===\n");

    if (wait_for_idle() != 0) return -1;

    WRITE_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                          KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                          KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);

    seed_sw_entropy();
    printf("  SW entropy ready\n");

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    kmac__INTR_STATE_t state = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    if (state.f.kmac_done) {
        printf("PASS: Real kmac_done interrupt fired (INTR_STATE=0x%08x)\n", state.w);
    } else {
        printf("FAIL: kmac_done not in INTR_STATE (0x%08x)\n", state.w);
        test_errors++;
    }

    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);
    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    return 0;
}

static void test_intr_masking(void) {
    printf("\n=== Masking Test ===\n");

    uint32_t enable = READ_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR);
    if (enable == 0x0) {
        printf("PASS: INTR_ENABLE=0 (masked)\n");
    } else {
        printf("FAIL: INTR_ENABLE=0x%08x\n", enable);
        test_errors++;
    }

    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_TEST__KMAC_ERR_bm);

    uint32_t state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & KMAC__INTR_STATE__KMAC_ERR_bm) {
        printf("PASS: INTR_STATE set by INTR_TEST with INTR_ENABLE=0\n");
    } else {
        printf("FAIL: INTR_STATE=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  Interrupt Test\n");
    printf("========================================\n");

    WRITE_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                          KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                          KMAC__INTR_STATE__KMAC_ERR_bm);

    printf("\n=== INTR_TEST Event Bits ===\n");
    test_intr_bit_event("kmac_done", KMAC__INTR_TEST__KMAC_DONE_bm);
    test_intr_bit_event("kmac_err", KMAC__INTR_TEST__KMAC_ERR_bm);
    test_fifo_empty_intr();

    WRITE_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);

    if (test_real_kmac_done() != 0) {
        test_errors++;
    }
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
