/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Test fixture: confirms with the correct tag but the challenge's low bit flipped.

#include "smc_bl1.h"

int main(void) {
    uint32_t challenge[2];

    if (smc_bl1_receive_challenge(challenge) != 0u) return 0;
    challenge[0] ^= 1u;
    smc_bl1_send_confirmation(SMU_BL1_TAG_SMC, challenge);
    smc_bl1_post(SMC_BL1_CONFIRM_SENT);
    return 0;
}
