/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Convenience include for SMC DV firmware tests.
 *
 * Aggregates register access helpers, virtual console output, and
 * scratch/postcode helpers.
 */

#ifndef SMC_DEFINES_H
#define SMC_DEFINES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "virt_console.h"   /* simputs, simputshex32, simputshex64, simputsint */
#include "smc_reg_access.h" /* read_reg, write_reg, read_reg_64, write64_reg  */
#include "smc_cpu_ctrl.h"   /* write_scratch, read_scratch, write_postcode     */
#include "smc_cla_boot.h"   /* smu_sep_program_real_cla_boot                   */

#endif /* SMC_DEFINES_H */
