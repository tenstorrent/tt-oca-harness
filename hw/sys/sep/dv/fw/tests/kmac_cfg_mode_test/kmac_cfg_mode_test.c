/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_004 (P0) - CFG Mode/Kstrength Field Verification
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

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.SHA3_IDLE) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static void write_cfg_and_verify(const char *label, uint32_t kmac_en, uint32_t mode,
                                 uint32_t kstrength, uint32_t entropy_mode, uint32_t msg_endian,
                                 uint32_t state_endian) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = kmac_en;
    cfg.f.MODE = mode;
    cfg.f.KSTRENGTH = kstrength;
    cfg.f.ENTROPY_MODE = entropy_mode;
    cfg.f.MSG_ENDIANNESS = msg_endian;
    cfg.f.STATE_ENDIANNESS = state_endian;
    cfg.f.ENTROPY_READY = 0;

    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    kmac__CFG_SHADOWED_t rb = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR)};

    int pass = 1;
    if (rb.f.KMAC_EN != kmac_en) pass = 0;
    if (rb.f.MODE != mode) pass = 0;
    if (rb.f.KSTRENGTH != kstrength) pass = 0;
    if (rb.f.ENTROPY_MODE != entropy_mode) pass = 0;
    if (rb.f.MSG_ENDIANNESS != msg_endian) pass = 0;
    if (rb.f.STATE_ENDIANNESS != state_endian) pass = 0;

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
    printf("  TC_KMAC_004: CFG Mode Test\n");
    printf("========================================\n");

    if (wait_for_idle() != 0) {
        printf("FAIL: KMAC not idle at start\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* SHA3 mode, L128 strength */
    write_cfg_and_verify("SHA3/L128", 0, 0x0, 0x0, 0x1, 0, 0);

    /* SHA3 mode, L256 strength */
    write_cfg_and_verify("SHA3/L256", 0, 0x0, 0x2, 0x1, 0, 0);

    /* SHAKE mode, L128 */
    write_cfg_and_verify("SHAKE/L128", 0, 0x2, 0x0, 0x1, 0, 0);

    /* SHAKE mode, L256 */
    write_cfg_and_verify("SHAKE/L256", 0, 0x2, 0x2, 0x1, 0, 0);

    /* cSHAKE mode, L128 (mode=3 per hjson sha3_mode_e::CShake=2'b11) */
    write_cfg_and_verify("cSHAKE/L128", 0, 0x3, 0x0, 0x1, 0, 0);

    /* KMAC enabled, cSHAKE mode, L128 (mode=3 per hjson) */
    write_cfg_and_verify("KMAC_EN/cSHAKE/L128", 1, 0x3, 0x0, 0x1, 0, 0);

    /* KMAC enabled, cSHAKE mode, L256 (mode=3 per hjson) */
    write_cfg_and_verify("KMAC_EN/cSHAKE/L256", 1, 0x3, 0x2, 0x1, 0, 0);

    /* Test endianness flags */
    write_cfg_and_verify("msg_endian=1", 0, 0x0, 0x2, 0x1, 1, 0);

    write_cfg_and_verify("state_endian=1", 0, 0x0, 0x2, 0x1, 0, 1);

    write_cfg_and_verify("both_endian=1", 0, 0x0, 0x2, 0x1, 1, 1);

    /* Entropy mode: EDN (0x1 per hjson: 0=None, 1=EDN, 2=SW) */
    write_cfg_and_verify("entropy_mode=EDN", 0, 0x0, 0x2, 0x1, 0, 0);

    /* Restore default */
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, 0u);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, 0u);

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
