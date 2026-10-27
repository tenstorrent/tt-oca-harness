/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "bl1_message.h"
#include "sep_bl1_status.h"
#include "smu_bl1_contract.h"
#include "unit.h"

void test_message(void) {
    const uint64_t challenge = 0x0123456789ABCDEFull;
    uint32_t m[BL1_MSG_WORDS] = {0};

    bl1_challenge_message(challenge, m);
    CHECK_EQ(m[0], SMU_BL1_TAG_SEP);
    CHECK_EQ(m[1], 0x89ABCDEFu);
    CHECK_EQ(m[2], 0x01234567u);

    const uint32_t good[3] = {SMU_BL1_TAG_SMC, 0x89ABCDEFu, 0x01234567u};
    CHECK_EQ(bl1_check_confirmation(good, 3, challenge), BL1_OK);

    const uint32_t bad_tag[3] = {SMU_BL1_TAG_SEP, 0x89ABCDEFu, 0x01234567u};
    const uint32_t bad_lo[3] = {SMU_BL1_TAG_SMC, 0x89ABCDEEu, 0x01234567u};
    const uint32_t bad_hi[3] = {SMU_BL1_TAG_SMC, 0x89ABCDEFu, 0x81234567u};
    const uint32_t swapped[3] = {SMU_BL1_TAG_SMC, 0x01234567u, 0x89ABCDEFu};
    const uint32_t extra[4] = {0x0, SMU_BL1_TAG_SMC, 0x89ABCDEFu, 0x01234567u};
    CHECK_EQ(bl1_check_confirmation(bad_tag, 3, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(bad_lo, 3, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(bad_hi, 3, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(swapped, 3, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(good, 2, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(extra, 4, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(NULL, 3, challenge), SEP_BL1_ERR_CONFIRM_BAD);
    CHECK_EQ(bl1_check_confirmation(good, 3, challenge ^ 1u), SEP_BL1_ERR_CONFIRM_BAD);
}
