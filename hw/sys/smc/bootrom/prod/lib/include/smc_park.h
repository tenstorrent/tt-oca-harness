/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Hart 0 park interlock with the SEP. After the early MBIST and memory-repair checks, every
 * stop of hart 0 (a boot halt, AuthenticateImage, a park request, a trap) ends in
 * smc_park_hart0(), which disables interrupts, writes back the L1 D-cache, sets HART0_PARKED
 * in scratch 9 and loops on wfi. The SEP may then reset hart 0 without losing SRAM writes. */

#ifndef SMC_PARK_H
#define SMC_PARK_H

#include <stdbool.h>
#include "smc_defines.h"
#include "smc_rom_defs.h"

__attribute__((noreturn)) void smc_park_hart0(void);

/* True when the SEP has written the park request value to scratch 3. */
static inline bool smc_park_requested(void) {
    return read_scratch(SMC_SCRATCH_PARK_REQ) == SMC_PARK_REQ_VALUE;
}

#endif /* SMC_PARK_H */
