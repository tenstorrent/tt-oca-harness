/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Emergency Wipe Test.
 *
 * KMAC does not expose a dedicated WIPE_SECRET register in this SEP map. Use
 * the SEP reset controller KMAC software reset as the emergency wipe path:
 *   1) Generate non-zero KMAC state from a SHA3 operation.
 *   2) Assert and release KMAC SW reset.
 *   3) Verify reset defaults and functional recovery.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_kmac_p2_emergency_wipe_test STACK=cgen,sim
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define RST_KMAC (1u << 4)

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__none__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_STATUS_BASE_ADDR)};
        if (status.f.SHA3_IDLE) {
            return 0;
        }
    }

    printf("  Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__none__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_INTR_STATE_BASE_ADDR)};
        if (intr.f.KMAC_DONE) {
            WRITE_REG(OCH_SEP_TOP_KMAC_NONE_INTR_STATE_BASE_ADDR, intr.w);
            return 0;
        }
    }

    printf("  Timeout waiting for KMAC done\n");
    return -1;
}

static void seed_entropy(void) {
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_NONE_ENTROPY_SEED_BASE_ADDR, 0xdeadbeefu + (uint32_t)i);
    }
}

static void write_cfg_shadowed(kmac__none__CFG_SHADOWED_t cfg) {
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
}

static int run_sha3(uint32_t *digest0_out) {
    if (wait_for_idle() != 0) {
        return -1;
    }

    kmac__none__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 0;
    cfg.f.MODE = 0x0;
    cfg.f.KSTRENGTH = 0x2;
    cfg.f.ENTROPY_MODE = 0x1;
    write_cfg_shadowed(cfg);

    seed_entropy();
    cfg.f.ENTROPY_READY = 1;
    write_cfg_shadowed(cfg);

    kmac__none__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_MSG_FIFO_BASE_ADDR(0), 0x74736574u);
    cmd.f.CMD = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) {
        return -1;
    }

    uint32_t digest0 = READ_REG(OCH_SEP_TOP_KMAC_NONE_STATE_BASE_ADDR(0)) ^
                       READ_REG(OCH_SEP_TOP_KMAC_NONE_STATE_BASE_ADDR(0) + 0x100);
    printf("  digest0=0x%08x\n", digest0);
    *digest0_out = digest0;

    cmd.f.CMD = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CMD_BASE_ADDR, cmd.w);

    return (digest0 != 0) ? 0 : -1;
}

static void pulse_kmac_reset(void) {
    uint32_t sw_reset_n = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, sw_reset_n & ~RST_KMAC);
    for (volatile int i = 0; i < 64; i++) {
        __asm__ volatile("nop");
    }
    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, sw_reset_n | RST_KMAC);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("KMAC P2 Emergency Wipe Test\n");
    printf("========================================\n");

    int pass = 1;
    uint32_t digest_before = 0;
    uint32_t digest_after = 0;

    printf("\nStep 1: Produce non-zero KMAC state\n");
    if (run_sha3(&digest_before) != 0) {
        printf("  FAIL: initial SHA3 operation failed\n");
        pass = 0;
    }

    printf("\nStep 2: Assert/release KMAC SW reset as emergency wipe\n");
    pulse_kmac_reset();
    if (wait_for_idle() != 0) {
        pass = 0;
    }

    kmac__none__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_STATUS_BASE_ADDR)};
    kmac__none__CFG_REGWEN_t regwen = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_CFG_REGWEN_BASE_ADDR)};
    printf("  STATUS=0x%08x idle=%u empty=%u CFG_REGWEN=%u\n", status.w, status.f.SHA3_IDLE,
           status.f.FIFO_EMPTY, regwen.f.EN);
    if (!status.f.SHA3_IDLE || !status.f.FIFO_EMPTY || !regwen.f.EN) {
        printf("  FAIL: KMAC did not return to reset defaults after emergency wipe\n");
        pass = 0;
    }

    printf("\nStep 3: Functional recovery after wipe\n");
    if (pass && run_sha3(&digest_after) != 0) {
        printf("  FAIL: post-wipe SHA3 operation failed\n");
        pass = 0;
    }

    printf("  digest_before=0x%08x digest_after=0x%08x\n", digest_before, digest_after);

    printf("\n========================================\n");
    if (pass) {
        printf("=== KMAC P2 EMERGENCY WIPE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== KMAC P2 EMERGENCY WIPE TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
