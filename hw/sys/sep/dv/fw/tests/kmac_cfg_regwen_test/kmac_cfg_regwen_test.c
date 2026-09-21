/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * CFG_REGWEN Protection Test
 *
 * Verifies that CFG_REGWEN locks CFG_SHADOWED when KMAC is active
 * and unlocks after operation completes.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        if (READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & KMAC__INTR_STATE__KMAC_DONE_bm) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
            return 0;
        }
    }
    printf("Timeout waiting for done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static int test_cfg_regwen(void) {
    int errors = 0;

    printf("=== Step 1: Check CFG_REGWEN default (expect 1) ===\n");
    kmac__CFG_REGWEN_t rw = {.w = READ_REG(SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR)};
    printf("CFG_REGWEN = %u\n", rw.f.en);
    if (rw.f.en != 1) {
        printf("FAIL: expected en=1 at idle\n");
        errors++;
    }

    printf("=== Step 2: Verify CFG_SHADOWED writable when idle ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    uint32_t rb = READ_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    printf("CFG_SHADOWED written=0x%08x readback=0x%08x\n", cfg.w, rb);
    if (rb != cfg.w) {
        printf("FAIL: CFG_SHADOWED not writable when idle\n");
        errors++;
    }

    printf("=== Step 3: Configure and START (SHA3-256) ===\n");
    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    setup_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    printf("=== Step 4: Check CFG_REGWEN after START (expect 0) ===\n");
    rw.w = READ_REG(SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR);
    printf("CFG_REGWEN = %u\n", rw.f.en);
    if (rw.f.en != 0) {
        printf("FAIL: expected en=0 during operation\n");
        errors++;
    }

    printf("=== Step 5: Attempt to modify CFG_SHADOWED (should be blocked) ===\n");
    uint32_t saved_cfg = READ_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);

    kmac__CFG_SHADOWED_t alt_cfg = {.w = 0};
    alt_cfg.f.kmac_en = 0;
    alt_cfg.f.mode = SEP_KMAC_MODE_RESERVED;
    alt_cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    alt_cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    alt_cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, alt_cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, alt_cfg.w);

    uint32_t after_write = READ_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    printf("CFG_SHADOWED before=0x%08x attempted=0x%08x after=0x%08x\n", saved_cfg, alt_cfg.w,
           after_write);
    if (after_write != saved_cfg) {
        printf("FAIL: CFG_SHADOWED changed while REGWEN=0\n");
        errors++;
    } else {
        printf("PASS: CFG_SHADOWED protected\n");
    }

    printf("=== Step 6: Complete operation (PROCESS, wait done, DONE) ===\n");
    WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574);

    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    printf("=== Step 7: Check CFG_REGWEN after DONE (expect 1) ===\n");
    if (wait_for_idle() != 0) return -1;

    rw.w = READ_REG(SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR);
    printf("CFG_REGWEN = %u\n", rw.f.en);
    if (rw.f.en != 1) {
        printf("FAIL: expected en=1 after DONE\n");
        errors++;
    }

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  CFG_REGWEN Test\n");
    printf("========================================\n\n");

    int result = test_cfg_regwen();

    if (result == 0) {
        printf("\n=== TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== TEST FAILED (errors=%d) ===\n", result);
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
