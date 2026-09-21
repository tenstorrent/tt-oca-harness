/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * STATE Share Verification Test
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

static int test_state_read(void) {
    int errors = 0;

    printf("=== Step 1: Configure SHA3-256 ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    setup_entropy();

    printf("=== Step 2: START ===\n");
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    printf("=== Step 3: Write exact 3-byte 'abc' to MSG_FIFO ===\n");
    {
        volatile uint8_t *fifo8 =
            (volatile uint8_t *)(uintptr_t)SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR;
        *fifo8 = (uint8_t)'a';
        *fifo8 = (uint8_t)'b';
        *fifo8 = (uint8_t)'c';
    }

    printf("=== Step 4: PROCESS ===\n");
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    printf("=== Step 5: Read STATE shares ===\n");
    uint32_t share0[8], share1[8], digest[8];

    for (int i = 0; i < 8; i++) share0[i] = READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4)));

    for (int i = 0; i < 8; i++)
        share1[i] =
            READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));

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

    printf("=== Step 6: Exact SHA3-256(abc) + share properties ===\n");

    /* NIST FIPS 202 SHA3-256("abc") as little-endian STATE words. */
    static const uint32_t expected[8] = {0xa75d983au, 0xb225e24fu, 0x2d175c04u, 0xbd90d36bu,
                                         0x6e085f85u, 0x5b529d3eu, 0x45e2bf46u, 0x32154311u};
    for (int i = 0; i < 8; i++) {
        if (digest[i] != expected[i]) {
            printf("FAIL: DIGEST_%d=0x%08x expected=0x%08x\n", i, digest[i], expected[i]);
            errors++;
        }
    }

    int s0_nz = 0, s1_nz = 0;
    for (int i = 0; i < 8; i++) {
        if (share0[i] != 0) s0_nz = 1;
        if (share1[i] != 0) s1_nz = 1;
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

    printf("=== Step 7: DONE ===\n");
    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  STATE Share Verify Test\n");
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
