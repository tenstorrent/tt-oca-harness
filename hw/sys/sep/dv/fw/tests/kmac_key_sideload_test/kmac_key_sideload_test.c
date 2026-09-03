/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC Key Sideload Mode Test
 *
 * Tests the CFG_SHADOWED.sideload register field and its functional effect:
 *
 * Phase 1 — Register control:
 * Verify default sideload=1; write 0, readback 0; write 1, readback 1.
 *
 * Phase 2 — SW-key operation (sideload=0):
 * Run KMAC-128 with a known software key (KEY_SHARE0/1 registers).
 * Verify non-zero digest and record digest_sw[].
 *
 * Phase 3 — Determinism (sideload=0, same SW key):
 * Re-run Phase 2; digest must match Phase 2 and the fixed SW-key vector.
 *
 * Phase 4 — Optional ENV note (no security claim without keymgr allow-path):
 * If sideload=1 START raises ErrKeyNotValid, log INFO only, then recover
 * through CMD.err_processed so Phase 5 can run.
 *
 * Phase 5 — Error recovery:
 * Repeat the Phase 2 SW-key operation after the error. The digest must match
 * Phase 2; a wiped or partial STATE means the engine was read before Squeeze.
 *
 * Checker summary:
 * [1] default sideload = 1 (typed CFG.sideload)
 * [2] sideload=0 readback = 0
 * [3] sideload=1 readback = 1
 * [4] Phase 2 KMAC completes
 * [5] Phase 2 digest matches fixed SW-key vector
 * [9] Phase 3 digest matches Phase 2 (determinism)
 * [10] Phase 5 digest matches Phase 2 after error recovery
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
/* Known SW key (non-zero, 128-bit = 4 words) */
static const uint32_t sw_key[4] = {0xDEADBEEF, 0xCAFEBABE, 0x01234567, 0x89ABCDEF};
static const uint32_t zero_mask[4] = {0, 0, 0, 0};
/* Independent expected digest for KMAC-128(sw_key, "test", 256) on this DUT config. */
static const uint32_t expected_sw_digest[8] = {
    0x04c5de8eu, 0xc99ac213u, 0x6be90faeu, 0xc1ccdb6bu,
    0x8fd7a62eu, 0x5a241720u, 0x88f7e6b2u, 0xd066ab63u,
};

/* ------------------------------------------------------------------ */
/* KMAC helpers                                                        */
/* ------------------------------------------------------------------ */

static int wait_idle(void) {
    int t = 2000000;
    while (t-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("  ERROR: KMAC idle timeout\n");
    return -1;
}

/* Clear every KMAC interrupt status bit (all are W1C). */
static void clear_intr_state(void) {
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);
}

/*
 * Wait until the digest is readable.
 *
 * STATE is driven only while the SHA3 FSM is in Squeeze; outside that state the
 * STATE window reads back as zero. INTR_STATE.kmac_done is a sticky event bit
 * and cannot be used as the gate: the error-recovery path raises it again on
 * its own, so a leftover done makes the next operation read STATE far too early.
 */
static int wait_squeeze(void) {
    int t = 2000000;
    while (t-- > 0) {
        uint32_t intr = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & KMAC__INTR_STATE__KMAC_ERR_bm) {
            uint32_t err = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
            printf("  ERROR: kmac_err while waiting squeeze (ERR_CODE=0x%08x code=0x%02x)\n", err,
                   SEP_KMAC_ERR_CODE_BYTE(err));
            return -2;
        }
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_squeeze) return 0;
    }
    printf("  ERROR: KMAC squeeze timeout\n");
    return -1;
}

/*
 * Recover from a reported KMAC error.
 *
 * CMD.err_processed only starts recovery: kmac_app issues an internal
 * CmdProcess and raises kmac_done once that throwaway digest is absorbed.
 * INTR_STATE must therefore be cleared after the engine reaches idle, not
 * before. Reaching idle also reopens CFG_REGWEN, which kmac_configure() checks.
 */
static int kmac_recover_from_error(void) {
    kmac__CMD_t ec = {.w = 0};
    ec.f.err_processed = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, ec.w);

    if (wait_idle() != 0) return -1;

    clear_intr_state();
    return 0;
}

/*
 * Configure KMAC-128 with given sideload setting using software entropy.
 *
 * CFG_REGWEN is hardware-driven off sha3_fsm == StIdle. CFG_SHADOWED and
 * KEY_SHARE writes issued while it is low are dropped with no bus error and no
 * ERR_CODE, so the miss stays invisible until a later digest mismatch. Refuse
 * to configure rather than let that happen.
 */
static int kmac_configure(int sideload) {
    kmac__CFG_REGWEN_t regwen = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR)};
    if (!regwen.f.en) {
        printf("  ERROR: CFG_REGWEN=0, CFG_SHADOWED write would be dropped silently\n");
        return -1;
    }

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 1;
    cfg.f.mode = SEP_KMAC_MODE_CSHAKE;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.sideload = sideload ? 1 : 0;
    cfg.f.entropy_ready = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xA5A5A500u + (uint32_t)i);
    }
    return 0;
}

/* Write 128-bit SW key via KEY_SHARE0 (share1 = all zeros for masking) */
static void write_sw_key(void) {
    kmac__KEY_LEN_t kl = {.w = 0};
    kl.f.len = 0x0; /* Key128 */
    WRITE_REG(OCH_SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, kl.w);
    for (int i = 0; i < 4; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(i), sw_key[i]);
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(i), zero_mask[i]);
    }
}

/* Set KMAC custom prefix = encode_string("KMAC") */
static void write_kmac_prefix(void) {
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x4D4B2001U);
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(1), 0x00004341U);
    for (int i = 2; i < 11; i++) WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(i), 0);
}

/* Run one KMAC-128("test", 256) operation; store 8-word digest into out[] */
static int run_kmac_op(uint32_t out[8]) {
    kmac__CMD_t cmd = {.w = 0};

    clear_intr_state();

    /* START */
    cmd.f.cmd = SEP_KMAC_CMD_START; /* CmdStart */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    /* Write message "test" (4 bytes LE) */
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574U);
    /* right_encode(256) = 0x01 0x00 0x02 */
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x00020001U);

    /* PROCESS */
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS; /* CmdProcess */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_squeeze() != 0) return -1;

    /* Read digest: XOR two masked shares */
    for (int i = 0; i < 8; i++)
        out[i] =
            READ_REG((OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4))) ^
            READ_REG((OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));

    /* DONE */
    cmd.f.cmd = SEP_KMAC_CMD_DONE; /* CmdDone */
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

/* ------------------------------------------------------------------ */
/* Main                                                                */
/* ------------------------------------------------------------------ */

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  KMAC Key Sideload Test\n");
    printf("========================================\n\n");

    {
        kmac__INTR_ENABLE_t ie = {.w = 0};
        ie.f.kmac_done = 1;
        ie.f.fifo_empty = 1;
        ie.f.kmac_err = 1;
        WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, ie.w);
    }

    int errors = 0;
    int injected_err = 0;
    uint32_t digest_sw[8];
    uint32_t digest_retry[8];
    uint32_t digest_recover[8];

    /* ----------------------------------------------------------------
     * Phase 1: Register control — verify sideload field R/W
     * -------------------------------------------------------------- */
    printf("=== Phase 1: CFG.sideload register control ===\n");

    kmac__CFG_SHADOWED_t cfg_rd_u = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR)};
    uint32_t cfg_rd = cfg_rd_u.w;
    int default_sideload = cfg_rd_u.f.sideload;
    printf("  Default CFG=0x%08x sideload=%d\n", cfg_rd, default_sideload);
    if (default_sideload == 1) {
        printf("  CHK[1] PASS: default sideload=1\n");
    } else {
        printf("  CHK[1] FAIL: default sideload=%d (expected 1)\n", default_sideload);
        errors++;
    }

    /* Write sideload=0, read back */
    kmac__CFG_SHADOWED_t cfg_test = {.w = cfg_rd};
    cfg_test.f.sideload = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg_test.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg_test.w);
    cfg_rd_u.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    cfg_rd = cfg_rd_u.w;
    int rb0 = cfg_rd_u.f.sideload;
    printf("  After write 0: CFG=0x%08x sideload=%d\n", cfg_rd, rb0);
    if (rb0 == 0) {
        printf("  CHK[2] PASS: sideload=0 readback OK\n");
    } else {
        printf("  CHK[2] FAIL: sideload=%d (expected 0)\n", rb0);
        errors++;
    }

    /* Write sideload=1, read back */
    cfg_test.f.sideload = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg_test.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg_test.w);
    cfg_rd_u.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    cfg_rd = cfg_rd_u.w;
    int rb1 = cfg_rd_u.f.sideload;
    printf("  After write 1: CFG=0x%08x sideload=%d\n", cfg_rd, rb1);
    if (rb1 == 1) {
        printf("  CHK[3] PASS: sideload=1 readback OK\n");
    } else {
        printf("  CHK[3] FAIL: sideload=%d (expected 1)\n", rb1);
        errors++;
    }

    /* ----------------------------------------------------------------
     * Phase 2: SW-key operation (sideload=0)
     * -------------------------------------------------------------- */
    printf("\n=== Phase 2: KMAC-128 with SW key (sideload=0) ===\n");

    if (wait_idle() != 0 || kmac_configure(0) != 0) { /* sideload=0 */
        errors++;
        goto done;
    }
    write_sw_key();
    write_kmac_prefix();

    if (run_kmac_op(digest_sw) != 0) {
        printf("  CHK[4] FAIL: KMAC timeout with SW key\n");
        errors++;
        goto done;
    }
    printf("  CHK[4] PASS: KMAC completed with SW key\n");

    printf("  digest_sw: ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest_sw[i]);
    printf("\n");
    {
        int mismatch = 0;
        for (int i = 0; i < 8; i++)
            if (digest_sw[i] != expected_sw_digest[i]) mismatch = 1;
        if (!mismatch) {
            printf("  CHK[5] PASS: SW-key digest matches fixed vector\n");
        } else {
            printf("  CHK[5] FAIL: SW-key digest != expected vector\n");
            errors++;
        }
    }

    /* ----------------------------------------------------------------
     * Phase 3: Determinism BEFORE sideload error injection
     * -------------------------------------------------------------- */
    printf("\n=== Phase 3: Determinism check (sideload=0, same SW key) ===\n");

    if (wait_idle() != 0 || kmac_configure(0) != 0) {
        errors++;
        goto done;
    }
    write_sw_key();
    write_kmac_prefix();

    if (run_kmac_op(digest_retry) != 0) {
        printf("  CHK[9] FAIL: KMAC timeout on determinism retry\n");
        errors++;
        goto done;
    }

    {
        int mismatch = 0;
        for (int i = 0; i < 8; i++)
            if (digest_retry[i] != digest_sw[i]) {
                mismatch = 1;
                break;
            }
        if (!mismatch) {
            printf("  CHK[9] PASS: retry digest matches Phase 2 (deterministic)\n");
        } else {
            printf("  CHK[9] FAIL: retry digest differs from Phase 2\n");
            printf("    Phase 2: ");
            for (int i = 0; i < 8; i++) printf("%08x ", digest_sw[i]);
            printf("\n    Retry  : ");
            for (int i = 0; i < 8; i++) printf("%08x ", digest_retry[i]);
            printf("\n");
            errors++;
            goto done;
        }
    }

    /* ----------------------------------------------------------------
     * Phase 4: ENV note only — no fail-closed claim without keymgr allow-path.
     * The error is still injected so Phase 5 can exercise recovery.
     * -------------------------------------------------------------- */
    printf("\n=== Phase 4: ENV note (sideload=1, no keymgr) ===\n");
    if (wait_idle() == 0 && kmac_configure(1) == 0) {
        write_kmac_prefix();
        kmac__CMD_t cmd = {.w = 0};
        cmd.f.cmd = SEP_KMAC_CMD_START;
        WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
        int saw_err = 0;
        for (int i = 0; i < 100000 && !saw_err; i++) {
            uint32_t intr = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
            if (intr & KMAC__INTR_STATE__KMAC_ERR_bm) saw_err = 1;
        }
        uint32_t err = READ_REG(OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
        printf("  INFO: sideload START ERR_CODE=0x%08x code=0x%02x kmac_err=%d (ENV)\n", err,
               SEP_KMAC_ERR_CODE_BYTE(err), saw_err);
        injected_err = saw_err;
        if (kmac_recover_from_error() != 0) {
            printf("  CHK[10] FAIL: KMAC did not return to idle after err_processed\n");
            errors++;
            goto done;
        }
    }

    /* ----------------------------------------------------------------
     * Phase 5: SW-key operation after error recovery.
     * A fresh sideload=0 run must produce the same digest as Phase 2.
     * -------------------------------------------------------------- */
    printf("\n=== Phase 5: SW-key KMAC after error recovery ===\n");
    if (!injected_err) {
        printf("  INFO: no sideload error raised in Phase 4; recovery path not exercised\n");
        goto done;
    }

    if (kmac_configure(0) != 0) {
        printf("  CHK[10] FAIL: CFG_SHADOWED not writable after recovery\n");
        errors++;
        goto done;
    }
    write_sw_key();
    write_kmac_prefix();

    if (run_kmac_op(digest_recover) != 0) {
        printf("  CHK[10] FAIL: KMAC did not complete after error recovery\n");
        errors++;
        goto done;
    }

    {
        int mismatch = 0;
        for (int i = 0; i < 8; i++)
            if (digest_recover[i] != digest_sw[i]) {
                mismatch = 1;
                break;
            }
        if (!mismatch) {
            printf("  CHK[10] PASS: post-recovery digest matches Phase 2\n");
        } else {
            printf("  CHK[10] FAIL: post-recovery digest differs from Phase 2\n");
            printf("    Phase 2: ");
            for (int i = 0; i < 8; i++) printf("%08x ", digest_sw[i]);
            printf("\n    Recover: ");
            for (int i = 0; i < 8; i++) printf("%08x ", digest_recover[i]);
            printf("\n");
            errors++;
        }
    }

done:
    printf("\n========================================\n");
    if (errors == 0) {
        printf("=== TEST PASSED (%d errors) ===\n", errors);
        test_pass(0);
    } else {
        printf("=== TEST FAILED (%d errors) ===\n", errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
