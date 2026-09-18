/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Emergency Wipe Test.
 *
 * KMAC does not expose a dedicated WIPE_SECRET register in this SEP map. Use
 * the SEP reset controller KMAC software reset as the emergency wipe path:
 *   1) Generate non-zero KMAC state from a SHA3 operation.
 *   2) Assert and release KMAC SW reset (poll idle; timeout FAIL).
 *   3) Prove post-reset STATE zeros + exact recovery digest.
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
#include "test_completion.h"

#define RST_KMAC SEP_RESET_CTRL__SW_RESET_N__KMAC_SW_RST_N_bm

/* Independent SHA3-256("test") as little-endian STATE words. */
static const uint32_t expected_sha3_test[8] = {
    0x5828f036u, 0xc82cb00bu, 0x029a2a27u, 0xe300420fu,
    0xae76e246u, 0xee454e66u, 0x74557480u, 0x80abf5e2u,
};

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

static void seed_entropy(void) {
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xdeadbeefu + (uint32_t)i);
    }
}

static void write_cfg_shadowed(kmac__CFG_SHADOWED_t cfg) {
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
}

static int read_digest(uint32_t digest_out[8]) {
    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (uint32_t)i * 4u);
        uint32_t s1 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET +
                               (uint32_t)i * 4u);
        digest_out[i] = s0 ^ s1;
    }
    return 0;
}

static int run_sha3(uint32_t digest_out[8]) {
    if (wait_for_idle() != 0) {
        return -1;
    }

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    write_cfg_shadowed(cfg);

    cfg.f.entropy_ready = 1;
    write_cfg_shadowed(cfg);
    seed_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574u); /* "test" LE */
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) {
        return -1;
    }

    read_digest(digest_out);
    printf("  digest0=0x%08x\n", digest_out[0]);

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    for (int i = 0; i < 8; i++) {
        if (digest_out[i] != expected_sha3_test[i]) {
            printf("  FAIL: DIGEST_%d=0x%08x expected=0x%08x\n", i, digest_out[i],
                   expected_sha3_test[i]);
            return -1;
        }
    }
    return 0;
}

static int pulse_kmac_reset(void) {
    uint32_t sw_reset_n = READ_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, sw_reset_n & ~RST_KMAC);
    /* Hold assert briefly then release; poll architecturally visible idle. */
    WRITE_REG(OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, sw_reset_n | RST_KMAC);

    if (wait_for_idle() != 0) {
        printf("  FAIL: timeout waiting for idle after KMAC SW reset release\n");
        return -1;
    }
    return 0;
}

static int state_is_zero(void) {
    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (uint32_t)i * 4u);
        uint32_t s1 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET +
                               (uint32_t)i * 4u);
        if (s0 != 0u || s1 != 0u) {
            printf("  FAIL: post-wipe STATE word %d share0=0x%08x share1=0x%08x (expected 0)\n", i,
                   s0, s1);
            return 0;
        }
    }
    return 1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("KMAC P2 Emergency Wipe Test\n");
    printf("========================================\n");

    int pass = 1;
    uint32_t digest_before[8];
    uint32_t digest_after[8];

    printf("\nStep 1: Produce known SHA3-256(test) state\n");
    if (run_sha3(digest_before) != 0) {
        printf("  FAIL: initial SHA3 operation failed\n");
        pass = 0;
    }

    printf("\nStep 2: Assert/release KMAC SW reset as emergency wipe\n");
    if (pass && pulse_kmac_reset() != 0) {
        pass = 0;
    }

    kmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    kmac__CFG_REGWEN_t regwen = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR)};
    printf("  STATUS=0x%08x idle=%u empty=%u CFG_REGWEN=%u\n", status.w, status.f.sha3_idle,
           status.f.fifo_empty, regwen.f.en);
    if (!status.f.sha3_idle || !status.f.fifo_empty || !regwen.f.en) {
        printf("  FAIL: KMAC did not return to reset defaults after emergency wipe\n");
        pass = 0;
    }
    if (pass && !state_is_zero()) {
        pass = 0;
    }

    printf("\nStep 3: Functional recovery after wipe\n");
    if (pass && run_sha3(digest_after) != 0) {
        printf("  FAIL: post-wipe SHA3 operation failed\n");
        pass = 0;
    }

    printf("  digest_before=0x%08x digest_after=0x%08x\n", digest_before[0], digest_after[0]);

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
