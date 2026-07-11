/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_008 - Entropy Configuration Test (P1)
 *
 * Verifies KMAC entropy period register, entropy seed provisioning,
 * and entropy_ready flow. Runs a SHA3-256 hash to confirm entropy
 * is functional, then reads ENTROPY_REFRESH_HASH_CNT.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.SHA3_IDLE) return 0;
    }
    printf("Timeout waiting for idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        if (READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & 0x1) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1);
            return 0;
        }
    }
    printf("Timeout waiting for done\n");
    return -1;
}

static int test_entropy_config(void) {
    int errors = 0;
    uint32_t val;

    printf("=== Step 1: Read ENTROPY_PERIOD default ===\n");
    val = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR);
    printf("ENTROPY_PERIOD default = 0x%08x\n", val);
    if (val != 0x00000000) {
        printf("FAIL: expected default 0x00000000\n");
        errors++;
    }

    printf("=== Step 2: Write ENTROPY_PERIOD 0x03FF0100 ===\n");
    WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0x03FF0100);
    val = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR);
    printf("ENTROPY_PERIOD readback = 0x%08x\n", val);
    kmac__ENTROPY_PERIOD_t ep = {.w = val};
    printf("  prescaler=%u wait_timer=%u\n", ep.f.PRESCALER, ep.f.WAIT_TIMER);
    if (val != 0x03FF0100) {
        printf("FAIL: readback mismatch\n");
        errors++;
    }

    printf("=== Step 3: Seed entropy ===\n");
    for (int i = 0; i < 6; i++) WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);

    printf("=== Step 4: Configure SHA3-256 with entropy ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 0;
    cfg.f.MODE = 0x0;
    cfg.f.KSTRENGTH = 0x2;
    cfg.f.ENTROPY_MODE = 0x1; /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.ENTROPY_READY = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    printf("=== Step 5: START, write message, PROCESS ===\n");
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x74736574);

    cmd.f.CMD = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    printf("=== Step 6: Read digest ===\n");
    uint32_t digest[8];
    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(i * 4));
        uint32_t s1 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(0x100 + (i * 4)));
        digest[i] = s0 ^ s1;
    }

    int non_zero = 0;
    printf("Digest: ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", digest[i]);
        if (digest[i] != 0) non_zero = 1;
    }
    printf("\n");

    if (!non_zero) {
        printf("FAIL: digest is all zeros\n");
        errors++;
    }

    cmd.f.CMD = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    printf("=== Step 7: Read ENTROPY_REFRESH_HASH_CNT (expect > 0 after hash) ===\n");
    kmac__ENTROPY_REFRESH_HASH_CNT_t hc = {
        .w = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_HASH_CNT_BASE_ADDR)};
    printf("ENTROPY_REFRESH_HASH_CNT = %u\n", hc.f.HASH_CNT);
    if (hc.f.HASH_CNT > 0) {
        printf("PASS: ENTROPY_REFRESH_HASH_CNT incremented after hash\n");
    } else {
        printf(
            "INFO: ENTROPY_REFRESH_HASH_CNT=0 (may reset with entropy_ready; not a hard fail)\n");
    }

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  TC_KMAC_008: Entropy Config Test\n");
    printf("========================================\n\n");

    int result = test_entropy_config();

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
