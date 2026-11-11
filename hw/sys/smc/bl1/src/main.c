/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Reference SMC BL1: answers the SEP BL1's challenge, then parks hart 0 (start.S).

#include "smc_bl1.h"

int main(void) {
    uint32_t challenge[2];

    smc_bl1_puts("SMC BL1\n");
    if (smc_bl1_receive_challenge(challenge) != 0u) return 0;
    smc_bl1_send_confirmation(SMU_BL1_TAG_SMC, challenge);
    smc_bl1_post(SMC_BL1_CONFIRM_SENT);
    smc_bl1_post(SMC_BL1_DONE);
    smc_bl1_puts("SMC BL1 done\n");
    return 0;
}
