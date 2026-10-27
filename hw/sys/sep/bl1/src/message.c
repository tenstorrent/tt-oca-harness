/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "bl1_message.h"

#include <stddef.h>

#include "harden.h"
#include "sep_bl1_status.h"
#include "smu_bl1_contract.h"

void bl1_challenge_message(uint64_t challenge, uint32_t out[BL1_MSG_WORDS]) {
    out[0] = SMU_BL1_TAG_SEP;
    out[1] = (uint32_t)challenge;
    out[2] = (uint32_t)(challenge >> 32);
}

bl1_result_t bl1_check_confirmation(const uint32_t *words, uint32_t count, uint64_t challenge) {
    if (words == NULL || count != BL1_MSG_WORDS) return SEP_BL1_ERR_CONFIRM_BAD;
    uint32_t diff = (words[0] ^ SMU_BL1_TAG_SMC) | (words[1] ^ (uint32_t)challenge) |
                    (words[2] ^ (uint32_t)(challenge >> 32));
    uint32_t diff2 = (harden_u32(words[0]) ^ SMU_BL1_TAG_SMC) |
                     (harden_u32(words[1]) ^ harden_u32((uint32_t)challenge)) |
                     (harden_u32(words[2]) ^ harden_u32((uint32_t)(challenge >> 32)));
    if ((diff | diff2) != 0u) return SEP_BL1_ERR_CONFIRM_BAD;
    return BL1_OK;
}
