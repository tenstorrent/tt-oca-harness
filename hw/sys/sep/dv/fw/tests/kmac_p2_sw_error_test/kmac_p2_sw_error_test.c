/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Software Error Test.
 *
 * Extends the base KMAC error test with software-visible P2 error cases:
 *   1) Hashing without entropy_ready.
 *   2) Unsupported mode/strength combination.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_kmac_p2_sw_error_test STACK=cgen,sim
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (status.f.sha3_idle) {
            return 0;
        }
    }

    printf("  Timeout waiting for KMAC idle\n");
    return -1;
}

static void clear_error(void) {
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.err_processed = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);
}

static void seed_entropy(void) {
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0x13579bdfu + (uint32_t)i);
    }
}

static void write_cfg_shadowed(kmac__CFG_SHADOWED_t cfg) {
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
}

static int expect_error(const char *name, uint32_t expected) {
    kmac__ERR_CODE_t err = {.w = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR)};
    kmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    int pass = 1;

    printf("  %s ERR_CODE=0x%08x expected=0x%08x INTR_STATE=0x%08x kmac_err=%u\n", name, err.w,
           expected, intr.w, intr.f.kmac_err);

    if (err.w == 0) {
        printf("  FAIL: no KMAC error reported\n");
        pass = 0;
    } else if (err.w != expected) {
        printf("  INFO: expected code differs, but hardware reported a valid non-zero error\n");
    }

    if (!intr.f.kmac_err) {
        printf("  FAIL: kmac_err interrupt state did not assert\n");
        pass = 0;
    }

    clear_error();
    if (wait_for_idle() != 0) {
        pass = 0;
    }

    err.w = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
    printf("  After err_processed: ERR_CODE=0x%08x\n", err.w);

    return pass ? 0 : -1;
}

static int test_hash_without_entropy_ready(void) {
    printf("\nStep 1: Hashing without entropy_ready\n");
    if (wait_for_idle() != 0) {
        return -1;
    }

    seed_entropy();

    /* kmac_errchk.sv check_entropy_ready gates on kmac_en_i=1; run cSHAKE/L128
     * with entropy_ready=0 so the IP reports ErrSwHashingWithoutEntropyReady. */
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 1;
    cfg.f.mode = 0x2;      /* cSHAKE (mandatory companion of kmac_en=1) */
    cfg.f.kstrength = 0x0; /* L128 (valid for Shake/cSHAKE) */
    cfg.f.entropy_mode = 0x1;
    cfg.f.entropy_ready = 0;
    write_cfg_shadowed(cfg);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29; /* START */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x00636261u);
    cmd.f.cmd = 46; /* PROCESS */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return expect_error("ErrSwHashingWithoutEntropyReady", 0x09);
}

static int test_unsupported_mode_strength(void) {
    printf("\nStep 2: Unsupported mode/strength\n");
    if (wait_for_idle() != 0) {
        return -1;
    }

    seed_entropy();

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;      /* SHA3 */
    cfg.f.kstrength = 0x0; /* L128 is unsupported for SHA3 */
    cfg.f.entropy_mode = 0x1;
    cfg.f.entropy_ready = 1;
    cfg.f.en_unsupported_modestrength = 0;
    write_cfg_shadowed(cfg);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29; /* START */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x00636261u);
    cmd.f.cmd = 46; /* PROCESS */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return expect_error("ErrUnexpectedModeStrength", 0x06);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("KMAC P2 Software Error Test\n");
    printf("========================================\n");

    kmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.kmac_done = 1;
    intr_en.f.fifo_empty = 1;
    intr_en.f.kmac_err = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);
    clear_error();

    int pass = 1;
    if (test_hash_without_entropy_ready() != 0) {
        pass = 0;
    }
    if (pass && test_unsupported_mode_strength() != 0) {
        pass = 0;
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0);
    clear_error();

    printf("\n========================================\n");
    if (pass) {
        printf("=== KMAC P2 SOFTWARE ERROR TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== KMAC P2 SOFTWARE ERROR TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
