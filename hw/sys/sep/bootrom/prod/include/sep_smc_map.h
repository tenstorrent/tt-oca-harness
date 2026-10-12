/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Offsets of the SMC registers SEP reaches through its SMC window, taken from
// the generated SMC map. Macro-only, so vector.S includes it as well as C.

#pragma once

#include "smc_addr.h"
#include "smc_local_base.h"

// The sep_local_axi_xbar routes [0x40000000, 0xC0000000) to
// sep_system_peripherals, which forwards to the SMC through the output fabric.
#define SEP_SMC_GLOBAL_BASE 0x40000000

// The SMC decodes its window from LOCAL_BASE, which SEP assumes holds its reset value.
#define SMC_OFFSET(smc_local_addr) ((smc_local_addr) - (SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset))

#define SMC_STRAPS_LO_OFFSET SMC_OFFSET(SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR)
#define SMC_STRAPS_HI_OFFSET SMC_OFFSET(SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_HI_BASE_ADDR)
#define SMC_SCRATCH_OFFSET(index) SMC_OFFSET(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR((index)))
#define SMC_CPU_CTRL_RESET_CTRL_OFFSET SMC_OFFSET(SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR)
#define SMC_CHIP_ID_OFFSET SMC_OFFSET(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR)
#define SMC_LC_STATE_OFFSET SMC_OFFSET(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR)
#define SMC_DFX_CTRL_STATUS_SMU_OFFSET SMC_OFFSET(SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR)
#define SMC_SRAM_OFFSET SMC_OFFSET(SMC_TOP_SPM_MEMORY_BASE_ADDR)
#define SMC_SRAM_SIZE_BYTES SMC_TOP_SPM_MEMORY_SIZE
