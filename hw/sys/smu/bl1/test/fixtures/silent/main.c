/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Test fixture: takes the challenge but never confirms, so the SEP BL1 times out.

#include "smc_bl1.h"

int main(void) {
    uint32_t challenge[2];

    smc_bl1_receive_challenge(challenge);
    return 0;
}
