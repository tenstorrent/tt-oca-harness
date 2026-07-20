/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Open smc_defines.h aggregator for the open SMC DV firmware tree.
 *
 * ROM tests ported from tt-oca-hw include "smc_defines.h" which in that repo
 * is a large header providing register access helpers, console output, and
 * register address macros.
 *
 * In the open harness those helpers come from the open include tree (already
 * on FW_INCLUDES).  Register address macros are provided by the open generated
 * headers (hw/sys/smc/regs/gen/c/ and hw/ip/<name>/regs/gen/c/) and any
 * per-test #ifndef guard fallbacks.
 *
 * This shim pulls in the three open headers whose combined surface matches
 * the helpers that tt-oca-hw's smc_defines.h provided.
 */

#ifndef SMC_DEFINES_H
#define SMC_DEFINES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "virt_console.h"    /* simputs, simputshex32, simputshex64, simputsint */
#include "smc_reg_access.h"  /* read_reg, write_reg, read_reg_64, write64_reg  */
#include "smc_cpu_ctrl.h"    /* write_scratch, read_scratch, write_postcode     */

#endif /* SMC_DEFINES_H */
