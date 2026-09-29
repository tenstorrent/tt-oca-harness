/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP eFuse FW shadow register read/write test.
 ******************************************************************************/

#include <stdint.h>
#include <stdio.h>

#include "efuse_fw_test_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

int main(void) {
    const uint32_t chiplet_pattern = 0xA5A55A5Au;
    const uint32_t class_pattern = 0x3C3CC3C3u;
    const uint32_t token_pattern = 0x13579BDFu;
    uint32_t original_class = 0;
    uint32_t original_token = 0;
    uint32_t token_after = 0;
    uint32_t rb = 0;

    sep_outbound_filter_init();

    printf("SEP eFuse FW Shadow RW Test\n");

    if (efuse_wait_sense_done() != 0) {
        test_fail(1);
    }

    printf("Checking normal shadow RW fields\n");
    if (efuse_shadow_rw32(SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR, chiplet_pattern,
                          "CHIPLET_UID[31:0]") != 0) {
        test_fail(1);
    }
    if (efuse_shadow_rw32(SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR, class_pattern,
                          "CLASS_KEY[31:0]") != 0) {
        test_fail(1);
    }

    printf("Checking secure_tm-sensitive shadow behavior with RMA_SIP_TOKEN_DIGEST\n");
    original_token = READ_REG(SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR);
    WRITE_REG(SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR, token_pattern);
    token_after = READ_REG(SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR);

    if (token_after == token_pattern) {
        printf("secure_tm-sensitive write allowed in current context; restoring token digest\n");
        WRITE_REG(SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR, original_token);
        rb = READ_REG(SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR);
        if (rb != original_token) {
            printf("ERROR: RMA_SIP_TOKEN_DIGEST restore expected=0x%08x got=0x%08x\n",
                   original_token, rb);
            test_fail(1);
        }
    } else if (token_after == original_token || token_after == EFUSE_FW_DENY_WORD) {
        printf("secure_tm-sensitive write denied in current context, readback=0x%08x\n",
               token_after);
    } else {
        printf("ERROR: unexpected secure_tm-sensitive readback 0x%08x original=0x%08x\n",
               token_after, original_token);
        test_fail(1);
    }

    printf("Checking shadow write lock on CLASS_KEY\n");
    original_class = READ_REG(SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR);
    if (efuse_set_shadow_lock_bit(EFUSE_FW_WRITE_LOCK_BIT(EFUSE_FW_FIELD_CLASS_KEY)) != 0) {
        test_fail(1);
    }

    WRITE_REG(SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR, ~original_class);
    rb = READ_REG(SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR);
    if (rb != original_class) {
        printf("ERROR: CLASS_KEY write lock failed original=0x%08x readback=0x%08x\n",
               original_class, rb);
        test_fail(1);
    }

    printf("Checking shadow read lock on CHIPLET_UID\n");
    if (efuse_set_shadow_lock_bit(EFUSE_FW_READ_LOCK_BIT(EFUSE_FW_FIELD_CHIPLET_UID)) != 0) {
        test_fail(1);
    }

    rb = READ_REG(SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR);
    if (rb != EFUSE_FW_DENY_WORD) {
        printf("ERROR: CHIPLET_UID read lock expected 0x%08x got=0x%08x\n", EFUSE_FW_DENY_WORD, rb);
        test_fail(1);
    }

    printf("*** SEP eFuse FW Shadow RW Test PASSED ***\n");
    test_pass(0);
    while (1) {
        __asm__("wfi");
    }
}
