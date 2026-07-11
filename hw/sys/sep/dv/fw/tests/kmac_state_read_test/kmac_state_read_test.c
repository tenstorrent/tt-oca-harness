/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_013 - STATE Share Verification Test (P1)
 *
 * Runs SHA3-256 of "abc", reads both STATE shares (share0 and share1),
 * verifies that both are non-zero, they differ (masking is active),
 * and their XOR produces a non-zero digest.
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

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static int test_state_read(void) {
    int errors = 0;

    printf("=== Step 1: Configure SHA3-256 ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 0;
    cfg.f.MODE = 0x0;
    cfg.f.KSTRENGTH = 0x2;
    cfg.f.ENTROPY_MODE = 0x1; /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    setup_entropy();

    cfg.f.ENTROPY_READY = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    printf("=== Step 2: START ===\n");
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    printf("=== Step 3: Write 'abc' to MSG_FIFO ===\n");
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x00636261);

    printf("=== Step 4: PROCESS ===\n");
    cmd.f.CMD = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    printf("=== Step 5: Read STATE shares ===\n");
    uint32_t share0[8], share1[8], digest[8];

    for (int i = 0; i < 8; i++) share0[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(i * 4));

    for (int i = 0; i < 8; i++)
        share1[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(0x100 + (i * 4)));

    for (int i = 0; i < 8; i++) digest[i] = share0[i] ^ share1[i];

    printf("Share0: ");
    for (int i = 0; i < 8; i++) printf("%08x ", share0[i]);
    printf("\n");

    printf("Share1: ");
    for (int i = 0; i < 8; i++) printf("%08x ", share1[i]);
    printf("\n");

    printf("Digest: ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest[i]);
    printf("\n");

    printf("=== Step 6: Verify share properties ===\n");

    int s0_nz = 0, s1_nz = 0, d_nz = 0;
    for (int i = 0; i < 8; i++) {
        if (share0[i] != 0) s0_nz = 1;
        if (share1[i] != 0) s1_nz = 1;
        if (digest[i] != 0) d_nz = 1;
    }

    if (!s0_nz) {
        printf("FAIL: share0 is all zeros\n");
        errors++;
    } else {
        printf("PASS: share0 is non-zero\n");
    }

    if (!s1_nz) {
        printf("FAIL: share1 is all zeros\n");
        errors++;
    } else {
        printf("PASS: share1 is non-zero\n");
    }

    int shares_same = 1;
    for (int i = 0; i < 8; i++) {
        if (share0[i] != share1[i]) {
            shares_same = 0;
            break;
        }
    }
    if (shares_same) {
        printf("FAIL: share0 == share1 (masking not active)\n");
        errors++;
    } else {
        printf("PASS: share0 != share1 (masking active)\n");
    }

    if (!d_nz) {
        printf("FAIL: digest (XOR) is all zeros\n");
        errors++;
    } else {
        printf("PASS: digest is non-zero\n");
    }

    printf("=== Step 7: DONE ===\n");
    cmd.f.CMD = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  TC_KMAC_013: STATE Share Verify Test\n");
    printf("========================================\n\n");

    int result = test_state_read();

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
