/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * CFG Mode/Kstrength Field Verification
 *
 * Writes CFG_SHADOWED with different mode/kstrength combinations,
 * reads back and verifies each configuration.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static void write_cfg_and_verify(const char *label, uint32_t kmac_en, uint32_t mode,
                                 uint32_t kstrength, uint32_t entropy_mode, uint32_t msg_endian,
                                 uint32_t state_endian) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = kmac_en;
    cfg.f.mode = mode;
    cfg.f.kstrength = kstrength;
    cfg.f.entropy_mode = entropy_mode;
    cfg.f.msg_endianness = msg_endian;
    cfg.f.state_endianness = state_endian;
    cfg.f.entropy_ready = 0;

    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    kmac__CFG_SHADOWED_t rb = {.w = READ_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR)};

    int pass = 1;
    if (rb.f.kmac_en != kmac_en) pass = 0;
    if (rb.f.mode != mode) pass = 0;
    if (rb.f.kstrength != kstrength) pass = 0;
    if (rb.f.entropy_mode != entropy_mode) pass = 0;
    if (rb.f.msg_endianness != msg_endian) pass = 0;
    if (rb.f.state_endianness != state_endian) pass = 0;

    if (pass) {
        printf("PASS: %s cfg=0x%08x\n", label, rb.w);
    } else {
        printf("FAIL: %s wrote=0x%08x read=0x%08x\n", label, cfg.w, rb.w);
        test_errors++;
    }
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  CFG Mode Test\n");
    printf("========================================\n");

    if (wait_for_idle() != 0) {
        printf("FAIL: KMAC not idle at start\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* SHA3 mode, L128 strength */
    write_cfg_and_verify("SHA3/L128", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L128,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* SHA3 mode, L256 strength */
    write_cfg_and_verify("SHA3/L256", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* SHAKE mode, L128 */
    write_cfg_and_verify("SHAKE/L128", 0, SEP_KMAC_MODE_SHAKE, SEP_KMAC_KSTRENGTH_L128,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* SHAKE mode, L256 */
    write_cfg_and_verify("SHAKE/L256", 0, SEP_KMAC_MODE_SHAKE, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* cSHAKE mode, L128 */
    write_cfg_and_verify("cSHAKE/L128", 0, SEP_KMAC_MODE_CSHAKE, SEP_KMAC_KSTRENGTH_L128,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* KMAC enabled, cSHAKE mode, L128 */
    write_cfg_and_verify("KMAC_EN/cSHAKE/L128", 1, SEP_KMAC_MODE_CSHAKE, SEP_KMAC_KSTRENGTH_L128,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* KMAC enabled, cSHAKE mode, L256 */
    write_cfg_and_verify("KMAC_EN/cSHAKE/L256", 1, SEP_KMAC_MODE_CSHAKE, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* Test endianness flags */
    write_cfg_and_verify("msg_endian=1", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 1, 0);

    write_cfg_and_verify("state_endian=1", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 1);

    write_cfg_and_verify("both_endian=1", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 1, 1);

    /* Entropy mode: EDN */
    write_cfg_and_verify("entropy_mode=EDN", 0, SEP_KMAC_MODE_SHA3, SEP_KMAC_KSTRENGTH_L256,
                         SEP_KMAC_ENTROPY_MODE_EDN, 0, 0);

    /* Restore default */
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, 0u);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, 0u);

    printf("\n========================================\n");
    if (test_errors == 0) {
        printf("  RESULT: ALL TESTS PASSED\n");
        test_pass(0);
    } else {
        printf("  RESULT: %d TESTS FAILED\n", test_errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
