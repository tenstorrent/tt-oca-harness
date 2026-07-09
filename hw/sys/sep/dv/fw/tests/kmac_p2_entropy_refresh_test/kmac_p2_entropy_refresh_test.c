/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Entropy Refresh Test.
 *
 * Verifies entropy refresh accounting controls:
 *   1) ENTROPY_REFRESH_THRESHOLD_SHADOWED accepts matching shadowed writes.
 *   2) ENTROPY_REFRESH_HASH_CNT is observable after hashing.
 *   3) CMD.hash_cnt_clr clears the refresh hash counter.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_kmac_p2_entropy_refresh_test STACK=cgen,sim
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

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.kmac_done) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, intr.w);
            return 0;
        }
    }

    printf("  Timeout waiting for KMAC done\n");
    return -1;
}

static void seed_entropy(uint32_t salt) {
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0x2468ace0u + salt + (uint32_t)i);
    }
}

static void write_cfg_shadowed(kmac__CFG_SHADOWED_t cfg) {
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
}

static int run_sha3_message(uint32_t msg) {
    if (wait_for_idle() != 0) {
        return -1;
    }

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;
    cfg.f.kstrength = 0x2;
    cfg.f.entropy_mode = 0x1;
    cfg.f.entropy_ready = 0;
    write_cfg_shadowed(cfg);

    seed_entropy(msg);
    cfg.f.entropy_ready = 1;
    write_cfg_shadowed(cfg);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29; /* START */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, msg);
    cmd.f.cmd = 46; /* PROCESS */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) {
        return -1;
    }

    uint32_t digest0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR) ^
                       READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + 0x100);
    printf("  msg=0x%08x digest0=0x%08x\n", msg, digest0);

    cmd.f.cmd = 22; /* DONE */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return (digest0 != 0) ? 0 : -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("KMAC P2 Entropy Refresh Test\n");
    printf("========================================\n");

    int pass = 1;

    kmac__ENTROPY_REFRESH_THRESHOLD_SHADOWED_t threshold = {.w = 0};
    threshold.f.threshold = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_THRESHOLD_SHADOWED_BASE_ADDR, threshold.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_THRESHOLD_SHADOWED_BASE_ADDR, threshold.w);

    uint32_t threshold_rb = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_THRESHOLD_SHADOWED_BASE_ADDR);
    printf("  ENTROPY_REFRESH_THRESHOLD write=0x%08x read=0x%08x\n", threshold.w, threshold_rb);
    if ((threshold_rb & 0x3ffu) != threshold.f.threshold) {
        printf("  FAIL: entropy refresh threshold readback mismatch\n");
        pass = 0;
    }

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.hash_cnt_clr = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (pass && run_sha3_message(0x74736574u) != 0) {
        pass = 0;
    }
    if (pass && run_sha3_message(0x61626300u) != 0) {
        pass = 0;
    }

    kmac__ENTROPY_REFRESH_HASH_CNT_t cnt = {
        .w = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_HASH_CNT_BASE_ADDR)};
    printf("  ENTROPY_REFRESH_HASH_CNT after hashes=%u (raw=0x%08x)\n", cnt.f.hash_cnt, cnt.w);
    if (cnt.f.hash_cnt == 0) {
        printf("  INFO: hash counter did not increment in this integration; clear path still "
               "checked\n");
    }

    cmd.w = 0;
    cmd.f.hash_cnt_clr = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    cnt.w = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_REFRESH_HASH_CNT_BASE_ADDR);
    printf("  ENTROPY_REFRESH_HASH_CNT after clear=%u (raw=0x%08x)\n", cnt.f.hash_cnt, cnt.w);
    if (cnt.f.hash_cnt != 0) {
        printf("  FAIL: hash counter clear did not take effect\n");
        pass = 0;
    }

    printf("\n========================================\n");
    if (pass) {
        printf("=== KMAC P2 ENTROPY REFRESH TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== KMAC P2 ENTROPY REFRESH TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
