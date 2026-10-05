/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Scratchpad Driver Implementation
 * Manages scratch registers for SMC/SEP coordination per SMC ROM Boot Architecture Specification.
 * SRAM protection status is handled in boot/sram_init.S during autozeroisation.
 */

#include "smc_scratchpad.h"
#include "smc_defines.h"
#include "virt_console.h"
#include "smc_post_code.h"

/*
 * SMC/SEP Coordination Implementation
 */

void smc_scratchpad_init(void) {
    /* Coordination registers (8, 9, 11, 15) are cleared in early assembly
     * (__metal_clear_coordination_scratch_regs) to handle async SMC resets.
     * This function handles any remaining scratchpad setup if needed. */

    /* No additional initialization needed - coordination registers
     * already cleared in assembly for async reset safety */
}

void smc_scratchpad_set_manifest_offset(uint64_t manifest_addr) {
    /* Validate address is within accessible SRAM bounds (excluding ROM regions) */
    if (manifest_addr < SMC_SRAM_OCCP_BASE_ADDR || manifest_addr >= SMC_SRAM_STACK_LIMIT_ADDR) {
        simputshex64("Invalid manifest address - out of accessible SRAM range: ", manifest_addr);
        simputshex32("Valid accessible SRAM range: ", SMC_SRAM_OCCP_BASE_ADDR);
        simputshex32("Valid SRAM limit: ", SMC_SRAM_STACK_LIMIT_ADDR);
        /* Write invalid offset to indicate error */
        write_scratch(SMC_SCRATCH_MANIFEST_ADDR, SMC_SCRATCHPAD_INVALID_OFFSET);
        return;
    }

    uint32_t manifest_offset = manifest_addr - SMC_SRAM_BASE;
    write_scratch(SMC_SCRATCH_MANIFEST_ADDR, manifest_offset);
}

void smc_scratchpad_signal_manifest_ready(void) {
    uint32_t current_status = read_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP);
    current_status |= SMC_SEP_STATUS_MANIFEST_READY;
    write_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP, current_status);
    smc_post_code_mark_manifest_ready();
}

void smc_scratchpad_set_status_buffer_offset(uint32_t buffer_addr) {
    /* Validate address is within accessible SRAM bounds (excluding ROM regions) */
    if (buffer_addr < SMC_SRAM_OCCP_BASE_ADDR || buffer_addr >= SMC_SRAM_STACK_LIMIT_ADDR) {
        simputshex32("Invalid status buffer address - out of accessible SRAM range: ", buffer_addr);
        simputshex32("Valid accessible SRAM range: ", SMC_SRAM_OCCP_BASE_ADDR);
        simputshex32("Valid SRAM limit: ", SMC_SRAM_STACK_LIMIT_ADDR);
        /* Write invalid offset to indicate error */
        write_scratch(SMC_SCRATCH_STATUS_BUFFER_ADDR, SMC_SCRATCHPAD_INVALID_OFFSET);
        return;
    }

    uint32_t buffer_offset = buffer_addr - SMC_SRAM_BASE;
    write_scratch(SMC_SCRATCH_STATUS_BUFFER_ADDR, buffer_offset);
}

void smc_scratchpad_signal_status_buffer_ready(void) {
    uint32_t current_status = read_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP);
    current_status |= SMC_SEP_STATUS_BUFFER_READY;
    write_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP, current_status);
    smc_post_code_mark_status_buffer_ready();
}

void smc_scratchpad_set_mbist_failure(uint32_t mbist_value) {
    write_scratch(SMC_SCRATCH_MBIST_FAILURE, mbist_value);
}

void smc_scratchpad_set_sep_safe_sram_offset(uint32_t start_addr, uint32_t size) {
    /* Validate address and region are within accessible SRAM bounds (excluding ROM regions) */
    if (start_addr < SMC_SRAM_OCCP_BASE_ADDR || start_addr >= SMC_SRAM_STACK_LIMIT_ADDR ||
        size > (SMC_SRAM_STACK_LIMIT_ADDR - start_addr)) {
        simputshex32("Invalid SEP safe SRAM region - out of accessible bounds: ", start_addr);
        simputshex32("Region size: ", size);
        simputshex32("Region end: ", start_addr + size);
        simputshex32("Valid accessible SRAM range: ", SMC_SRAM_OCCP_BASE_ADDR);
        simputshex32("Valid SRAM limit: ", SMC_SRAM_STACK_LIMIT_ADDR);
        /* Write invalid offset to indicate error */
        write_scratch(SMC_SCRATCH_SEP_SAFE_SRAM_START, SMC_SCRATCHPAD_INVALID_OFFSET);
        write_scratch(SMC_SCRATCH_SEP_SAFE_SRAM_SIZE, 0);
        return;
    }

    /* Use separate scratch registers for simplified SEP consumption */
    uint32_t start_offset = start_addr - SMC_SRAM_BASE;
    write_scratch(SMC_SCRATCH_SEP_SAFE_SRAM_START, start_offset);
    write_scratch(SMC_SCRATCH_SEP_SAFE_SRAM_SIZE, size);
    smc_post_code_mark_sep_comm_active();
}

void smc_scratchpad_signal_sram_init_complete(void) {
    uint32_t current_status = read_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP);
    current_status |= SMC_SEP_STATUS_SRAM_INIT;
    write_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP, current_status);
    smc_post_code_mark_sram_ready();
}

uint32_t smc_scratchpad_get_smc_status_to_sep(void) {
    return read_scratch(SMC_SCRATCH_SMC_STATUS_TO_SEP);
}

/*
 * Simulation helper functions
 * These provide convenient access to simulation-specific scratch registers
 */

void smc_scratchpad_set_sim_post_code(uint32_t post_code) {
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, post_code);
}

void smc_scratchpad_set_sim_pass_fail(uint32_t pass_fail_code) {
    write_scratch(SMC_SCRATCH_SIM_PASS_FAIL, pass_fail_code);
}
