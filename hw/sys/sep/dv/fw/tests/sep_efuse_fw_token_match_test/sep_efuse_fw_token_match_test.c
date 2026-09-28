/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP eFuse FW token match test.
 ******************************************************************************/

#include <stdint.h>
#include <stdio.h>

#include "efuse_fw_test_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

int main(void) {
    const uint32_t zero_token[8] = {0};
    const uint32_t mismatch_token[8] = {
        0x00000001u, 0x00000000u, 0x00000000u, 0x00000000u,
        0x00000000u, 0x00000000u, 0x00000000u, 0x00000000u,
    };

    sep_outbound_filter_init();

    printf("SEP eFuse FW Token Match Test\n");

    if (efuse_wait_sense_done() != 0) {
        test_fail(1);
    }

    printf("Checking SEC_DISABLE zero-token match\n");
    efuse_write_8_words(SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_BASE_ADDR(0), zero_token);
    if (efuse_token_trigger_and_poll(EFUSE_MMR__TOKEN_EOP__SECURE_DISABLE_TOKEN_GO_bm,
                                     SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_BASE_ADDR,
                                     EFUSE_TOKEN_MATCH) != 0) {
        test_fail(1);
    }

    printf("Checking SEC_DISABLE non-zero token mismatch\n");
    efuse_write_8_words(SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_BASE_ADDR(0), mismatch_token);
    if (efuse_token_trigger_and_poll(EFUSE_MMR__TOKEN_EOP__SECURE_DISABLE_TOKEN_GO_bm,
                                     SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_BASE_ADDR,
                                     EFUSE_TOKEN_MISMATCH) != 0) {
        test_fail(1);
    }

    printf("*** SEP eFuse FW Token Match Test PASSED ***\n");
    test_pass(0);
    while (1) {
        __asm__("wfi");
    }
}
