/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include "rom_otp.h"

__attribute__((weak)) void rom_otp_on_change(uint32_t changed_mask) {
    (void)changed_mask;
}
