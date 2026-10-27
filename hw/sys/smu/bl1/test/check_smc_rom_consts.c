/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Compile-only check that the stage contract agrees with the SMC Boot ROM on the same tree.

#include "cpu_ctrl.h"
#include "smc_rom_defs.h"
#include "smc_status.h"
#include "smu_bl1_contract.h"

_Static_assert(SMU_BL1_SEP_ZONE_START == SEP_SAFE_SRAM_START,
               "SEP zone start differs from the SMC Boot ROM's SEP-safe range");
_Static_assert(SMU_BL1_SEP_ZONE_END == SEP_SAFE_SRAM_END,
               "SEP zone end differs from the SMC Boot ROM's SEP-safe range");
_Static_assert(SMU_BL1_SEP_ZONE_END <= SMC_STATUS_BUFFER_ADDR,
               "SEP zone overlaps the SMC Boot ROM's status rings");
_Static_assert(SMU_BL1_SMC_ROM_RESET_VECTOR == CPU_CTRL__RESET_VECTOR__VECTOR_reset,
               "SMC Boot ROM base differs from the RESET_VECTOR reset value");
_Static_assert(SMU_BL1_SCRATCH_STATUS_TO_SEP == SMC_SCRATCH_SMC_STATUS_TO_SEP &&
                   SMU_BL1_SCRATCH_STATUS_BUFFER == SMC_SCRATCH_STATUS_BUFFER_ADDR &&
                   SMU_BL1_SCRATCH_SAFE_START == SMC_SCRATCH_SEP_SAFE_SRAM_START &&
                   SMU_BL1_SCRATCH_SAFE_SIZE == SMC_SCRATCH_SEP_SAFE_SRAM_SIZE,
               "coordination register indices differ from the SMC Boot ROM");
_Static_assert(SMU_BL1_STATUS_SRAM_INIT == SMC_SEP_STATUS_SRAM_INIT &&
                   SMU_BL1_STATUS_BUFFER_READY == (1u << SMC_SEP_STATUS_BUFFER_READY_BIT),
               "coordination status bits differ from the SMC Boot ROM");
