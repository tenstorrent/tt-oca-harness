/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SMC/SEP coordination helpers for OROM.
//
// This provides optional observability channels via SMC scratch regs:
// - Scratch[1]: POST_CODE (bitfield status)
// - Scratch[2]: VIRTUAL_CONSOLE (byte stream)
// - Scratch[9]: SMC_STATUS_TO_SEP (coordination flags)
// - Scratch[11]: STATUS_BUFFER_ADDR (offset in SMC SRAM)
//
// NOTE: Accessing these requires SEP-visible SMC MMIO mapping and PMP permission.
// The SMC base address is read dynamically from sep_cpu_ctrl (see sep_smc_interface.h).

#pragma once

#include <stdint.h>

#include "sep_smc_interface.h"

// All scratch read/write functions and index definitions are provided by
// sep_smc_interface.h.  This header adds ROM-specific convenience aliases
// and constants only.

// Convenience aliases for ROM post code / virtual console scratch indices.
enum {
    SMC_SCRATCH_POST_CODE = SMC_SCRATCH_POST_CODE_IDX,
    SMC_SCRATCH_VIRT_CONSOLE = SMC_SCRATCH_VIRT_CONSOLE_IDX,
};
