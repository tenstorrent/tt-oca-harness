/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Scratchpad Driver
 * Manages scratch registers for SMC/SEP coordination per SMC ROM Boot Architecture Specification.
 */

#ifndef SMC_SCRATCHPAD_H
#define SMC_SCRATCHPAD_H

#include <stdint.h>
#include "smc_rom_defs.h"

/*
 * Scratch Register Allocation (per SMC ROM Boot Architecture Specification)
 *
 * Registers 0-7: Maintain value across watchdog resets
 * Registers 8-15: Reset on watchdog resets
 *
 * Register 8:  Manifest offset handoff from SMC ROM to SEP ROM (offset from SMC_SRAM_BASE)
 * Register 9:  SMC Status to SEP (coordination protocol)
 * Register 11: Offset of status reporting structure in SMC SRAM (offset from SMC_SRAM_BASE)
 * Register 13: SEP safe SRAM start offset (offset from SMC_SRAM_BASE)
 * Register 15: MBIST register value when MBIST fails
 */

/* Scratch register definitions from specification */
#define SMC_SCRATCH_SIM_PASS_FAIL 0    /* SIM: Pass/Fail <dev only> */
#define SMC_SCRATCH_SIM_POST_CODE 1    /* SIM: POST code <dev only> */
#define SMC_SCRATCH_SIM_VIRT_CONSOLE 2 /* SIM: Virtual console <dev only> */

/* Scratch register definitions are in smc_rom_defs.h for use in both C and assembly */

#define SMC_SCRATCHPAD_SIM_PASS_CODE 0xacafaca1 /* SIM: Test pass code */
#define SMC_SCRATCHPAD_SIM_FAIL_CODE 0xffffffff /* SIM: Test fail code */

/* Error codes for invalid address handling */
#define SMC_SCRATCHPAD_INVALID_OFFSET \
    0xFFFFFFFF /* Invalid offset marker for address validation failures */

/*
 * SMC Status to SEP (Scratch Register 9) Bitfield Definitions
 */
#define SMC_SEP_STATUS_SRAM_INIT_BIT 0      /* SMC SRAM initialized */
#define SMC_SEP_STATUS_MANIFEST_READY_BIT 1 /* Manifest ready */
#define SMC_SEP_STATUS_BUFFER_READY_BIT 2   /* Status buffer ready */
#define SMC_SEP_STATUS_SRAM_PROTECTED_BIT 3 /* SRAM protected */

#define SMC_SEP_STATUS_SRAM_INIT (1U << SMC_SEP_STATUS_SRAM_INIT_BIT)
#define SMC_SEP_STATUS_MANIFEST_READY (1U << SMC_SEP_STATUS_MANIFEST_READY_BIT)
#define SMC_SEP_STATUS_BUFFER_READY (1U << SMC_SEP_STATUS_BUFFER_READY_BIT)
#define SMC_SEP_STATUS_SRAM_PROTECTED (1U << SMC_SEP_STATUS_SRAM_PROTECTED_BIT)

/*
 * SMC/SEP Coordination API
 */

/**
 * Initialize SMC/SEP coordination scratch registers
 */
void smc_scratchpad_init(void);

/**
 * Set the manifest address for SEP ROM handoff (stores as offset from SMC_SRAM_BASE)
 * @param manifest_addr Address of manifest in SRAM (must be within SRAM bounds)
 * @note Validates address range; writes 0xFFFFFFFF on invalid address
 */
void smc_scratchpad_set_manifest_offset(uint64_t manifest_addr);

/**
 * Signal to SEP that manifest is ready
 */
void smc_scratchpad_signal_manifest_ready(void);

/**
 * Set the status buffer address for SEP ROM (stores as offset from SMC_SRAM_BASE)
 * @param buffer_addr Address of status ring buffer in SRAM (must be within SRAM bounds)
 * @note Validates address range; writes 0xFFFFFFFF on invalid address
 */
void smc_scratchpad_set_status_buffer_offset(uint32_t buffer_addr);

/**
 * Signal to SEP that status buffer is ready
 */
void smc_scratchpad_signal_status_buffer_ready(void);

/**
 * Set MBIST failure register value
 * @param mbist_value MBIST register value when failure occurs
 */
void smc_scratchpad_set_mbist_failure(uint32_t mbist_value);

/**
 * Set SEP safe SRAM region information for SEP scratchpad operations (stores start as offset from
 * SMC_SRAM_BASE) Uses separate scratch registers for simplified SEP consumption
 * @param start_addr Starting address of safe SRAM region for SEP (must be within SRAM bounds)
 * @param size Size of safe SRAM region in bytes
 * @note Validates address range; writes 0xFFFFFFFF and size 0 on invalid address
 */
void smc_scratchpad_set_sep_safe_sram_offset(uint32_t start_addr, uint32_t size);

/**
 * Signal to SEP that SRAM initialization is complete
 */
void smc_scratchpad_signal_sram_init_complete(void);

/**
 * Get current SMC status to SEP register value
 * @return Current status register value
 */
uint32_t smc_scratchpad_get_smc_status_to_sep(void);

/*
 * Simulation helper functions
 * Convenient access to simulation-specific scratch registers
 */

/**
 * Set simulation POST code (scratch register 1)
 * Note: For structured POST code management, use smc_post_code.h API instead
 * @param post_code POST code value for simulation tracking
 */
void smc_scratchpad_set_sim_post_code(uint32_t post_code);

/**
 * Set simulation pass/fail status (scratch register 0)
 * @param pass_fail_code Pass/fail code for simulation validation
 */
void smc_scratchpad_set_sim_pass_fail(uint32_t pass_fail_code);

/*
 * Note: SRAM initialization and protection status are handled in boot/sram_init.S
 * during autozeroisation process as per SMC ROM Boot Architecture Specification.
 */

#endif /* SMC_SCRATCHPAD_H */
