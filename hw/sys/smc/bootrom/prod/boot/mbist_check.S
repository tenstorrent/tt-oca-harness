// SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
/* SPDX-License-Identifier: Apache-2.0 */

/*
 * SMC Production ROM MBIST Status Check
 *
 * Early boot memory BIST (Built-In Self Test) status validation.
 * This code executes before any stack operations to ensure memory
 * integrity before proceeding with normal boot sequence.
 *
 * Context:
 * - ROM executes from ROM memory (0xC0040000) but uses SRAM (0xC0060000+) for stack/data
 * - SMU DFT status register (0xC000F800) reports memory repair and MBIST status
 * - Hardware boot sequence: eFuse → Memory_Repair → SMU_MBIST → ROM_Execution
 *
 * ROM validates the SMU DFT status before using SRAM for stack/data.
 */

#include "smc_rom_defs.h"

/* Keep it in metal.init section for early execution */
.section .text.metal.init.mbist
/* Disable linker relaxation to ensure consistent addressing */
.option push
.option norelax

/*
 * Weak default MBIST hook.
 *
 * This default intentionally does nothing so platform users can provide a
 * strong __metal_mbist_early_check implementation without editing entry.S.
 * Any override still runs before stack setup and must avoid stack/global data.
 */
.weak __metal_mbist_early_check
.type __metal_mbist_early_check, @function
__metal_mbist_early_check:
    ret

.option pop

/*
 * Weak default memory repair hook.
 *
 * This default intentionally does nothing so platform users can provide a
 * strong __metal_memory_repair_check implementation without editing entry.S.
 * Any override still runs before stack setup and must avoid stack/global data.
 */
.weak __metal_memory_repair_check
.type __metal_memory_repair_check, @function
__metal_memory_repair_check:
    ret
