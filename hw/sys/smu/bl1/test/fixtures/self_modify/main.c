/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Test fixture: confirms correctly, then changes one word inside its own image, which the
// SEP BL1's re-hash must catch.

#include "smc_bl1.h"

extern uint32_t _start[];

int main(void) {
    uint32_t challenge[2];

    if (smc_bl1_receive_challenge(challenge) != 0u) return 0;
    smc_bl1_send_confirmation(SMU_BL1_TAG_SMC, challenge);
    smc_bl1_post(SMC_BL1_CONFIRM_SENT);

    // The first word of _start has already run. smc_bl1_park writes the D-cache back, so the
    // change reaches SRAM before the SEP re-hashes it.
    volatile uint32_t *word = _start;
    *word = ~*word;
    return 0;
}
