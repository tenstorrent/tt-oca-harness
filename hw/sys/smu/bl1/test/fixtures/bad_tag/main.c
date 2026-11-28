/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Test fixture: echoes the challenge under the tag "SMC0" instead of "SMC1".

#include "smc_bl1.h"

int main(void) {
    uint32_t challenge[2];

    if (smc_bl1_receive_challenge(challenge) != 0u) return 0;
    smc_bl1_send_confirmation(0x534D4330u, challenge);
    smc_bl1_post(SMC_BL1_CONFIRM_SENT);
    return 0;
}
