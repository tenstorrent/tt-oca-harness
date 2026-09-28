/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SHAKE128 XOF Test
 *
 * Verifies SHAKE128 eXtendable Output Function operation:
 * performs first squeeze, issues MANUAL_RUN for second squeeze,
 * and confirms the two squeeze outputs differ.
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

static int wait_for_squeeze(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_squeeze) return 0;
    }
    printf("Timeout waiting for squeeze\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static void read_state(uint32_t *out, int words) {
    for (int i = 0; i < words; i++) {
        uint32_t s0 = READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4)));
        uint32_t s1 =
            READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));
        out[i] = s0 ^ s1;
    }
}

static int test_shake128_xof(void) {
    int errors = 0;

    printf("=== Step 1: Configure SHAKE128 ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHAKE;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
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

    printf("=== Step 3: Write message 'test' ===\n");
    WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574);

    printf("=== Step 4: PROCESS ===\n");
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_squeeze() != 0) return -1;

    printf("=== Step 5: First squeeze - read STATE ===\n");
    uint32_t first_squeeze[8];
    read_state(first_squeeze, 8);

    printf("First squeeze: ");
    for (int i = 0; i < 8; i++) printf("%08x ", first_squeeze[i]);
    printf("\n");

    /* Independent SHAKE128("test") first 32B / post-rate MANUAL_RUN next 32B (LE words). */
    static const uint32_t expected_first[8] = {0x9caab0d3u, 0x5625b7d8u, 0x63bcce22u, 0x407d861eu,
                                               0x01f6d693u, 0x39a59101u, 0xec5fc473u, 0x74c7079bu};
    static const uint32_t expected_second[8] = {0x7a993bd1u, 0x093456deu, 0xeb1a49aau, 0xf5db2392u,
                                                0x1c386d21u, 0xb1e2540au, 0xe642b269u, 0x7731d4adu};

    for (int i = 0; i < 8; i++) {
        if (first_squeeze[i] != expected_first[i]) {
            printf("FAIL: first DIGEST_%d=0x%08x expected=0x%08x\n", i, first_squeeze[i],
                   expected_first[i]);
            errors++;
        }
    }

    printf("=== Step 6: Issue MANUAL_RUN for second squeeze ===\n");
    cmd.f.cmd = SEP_KMAC_CMD_MANUAL_RUN;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_squeeze() != 0) {
        printf("FAIL: timeout waiting for second squeeze\n");
        return errors + 1;
    }

    printf("=== Step 7: Second squeeze - read STATE ===\n");
    uint32_t second_squeeze[8];
    read_state(second_squeeze, 8);

    printf("Second squeeze: ");
    for (int i = 0; i < 8; i++) printf("%08x ", second_squeeze[i]);
    printf("\n");

    for (int i = 0; i < 8; i++) {
        if (second_squeeze[i] != expected_second[i]) {
            printf("FAIL: second DIGEST_%d=0x%08x expected=0x%08x\n", i, second_squeeze[i],
                   expected_second[i]);
            errors++;
        }
    }

    printf("=== Step 8: Compare squeezes ===\n");
    int same = 1;
    for (int i = 0; i < 8; i++) {
        if (first_squeeze[i] != second_squeeze[i]) {
            same = 0;
            break;
        }
    }
    if (same) {
        printf("FAIL: first and second squeezes are identical\n");
        errors++;
    } else {
        printf("PASS: squeezes differ as expected\n");
    }

    printf("=== Step 9: DONE ===\n");
    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  SHAKE128 XOF Test\n");
    printf("========================================\n\n");

    int result = test_shake128_xof();

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
