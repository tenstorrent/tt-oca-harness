/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Software Error Test.
 *
 *   1) Hashing without entropy_ready -> ErrSwHashingWithoutEntropyReady
 *   2) Unsupported mode/strength -> ErrUnexpectedModeStrength
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
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
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
}

static void write_cfg_shadowed(kmac__CFG_SHADOWED_t cfg) {
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
}

static int assert_allow_path(const char *tag) {
    /* OT: ERR_CODE is sticky; only require kmac_err==0 on the allow-path. */
    kmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    uint32_t err = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
    if (intr.f.kmac_err) {
        printf("  FAIL: %s allow-path dirty kmac_err=1 (ERR_CODE=0x%08x)\n", tag, err);
        return -1;
    }
    printf("  %s allow-path clean (kmac_err=0, sticky ERR_CODE=0x%08x) - PASS\n", tag, err);
    return 0;
}

static int run_legal_empty_sha3(void) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    write_cfg_shadowed(cfg);

    cfg.f.entropy_ready = 1;
    write_cfg_shadowed(cfg);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0x13579bdfu + (uint32_t)i);
    }

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.kmac_done) break;
    }
    if (timeout <= 0) {
        printf("  FAIL: legal SHA3 timeout\n");
        return -1;
    }
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    clear_error();
    return wait_for_idle();
}

static int expect_error(const char *name, uint32_t expected_code) {
    uint32_t err = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
    uint32_t code = SEP_KMAC_ERR_CODE_BYTE(err);
    kmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    int pass = 1;

    printf("  %s ERR_CODE=0x%08x code=0x%02x expected=0x%02x kmac_err=%u\n", name, err, code,
           expected_code, intr.f.kmac_err);

    if (code != expected_code) {
        printf("  FAIL: ERR_CODE byte mismatch\n");
        pass = 0;
    }
    if (!intr.f.kmac_err) {
        printf("  FAIL: kmac_err interrupt state did not assert\n");
        pass = 0;
    }

    clear_error();
    if (wait_for_idle() != 0) {
        pass = 0;
    }
    return pass ? 0 : -1;
}

static int test_hash_without_entropy_ready(void) {
    printf("\nStep 1: Hashing without entropy_ready\n");
    if (wait_for_idle() != 0) return -1;
    if (assert_allow_path("before entropy_ready negative") != 0) return -1;

    /* Ensure CFG_SHADOWED is writable after the legal SHA3 op. */
    kmac__CFG_REGWEN_t regwen = {.w = 0};
    regwen.f.en = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR, regwen.w);

    /*
     * PREFIX = encode_string("KMAC") || encode_string("").
     * First 6B must match EncodedStringKMAC or err_prefix (0x07) beats 0x09.
     */
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x4D4B2001U);
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(1), 0x00014341U);
    for (int i = 2; i < 11; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(i), 0);
    }
    kmac__KEY_LEN_t kl = {.w = 0};
    kl.f.len = 0x0;
    WRITE_REG(OCH_SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, kl.w);

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 1;
    cfg.f.mode = SEP_KMAC_MODE_CSHAKE;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    cfg.f.sideload = 0;
    write_cfg_shadowed(cfg);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    /* Check immediately — do not PROCESS (would overwrite ERR_CODE with 0x08). */
    return expect_error("ErrSwHashingWithoutEntropyReady",
                        SEP_KMAC_ERR_SW_HASHING_WITHOUT_ENTROPY_READY);
}

static int test_unsupported_mode_strength(void) {
    printf("\nStep 2: Unsupported mode/strength\n");
    if (wait_for_idle() != 0) return -1;
    if (assert_allow_path("before mode/strength negative") != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128; /* unsupported for SHA3 */
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 1;
    cfg.f.en_unsupported_modestrength = 0;
    write_cfg_shadowed(cfg);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0x13579bdfu + (uint32_t)i);
    }

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    /* Check immediately — MSG/PROCESS after rejected START yields ErrSwCmdSequence(0x08). */
    return expect_error("ErrUnexpectedModeStrength", SEP_KMAC_ERR_UNEXPECTED_MODE_STRENGTH);
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
    if (run_legal_empty_sha3() != 0 || assert_allow_path("initial legal hash") != 0) {
        pass = 0;
    }
    if (pass && test_hash_without_entropy_ready() != 0) {
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
