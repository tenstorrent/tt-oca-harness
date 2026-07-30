/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC POST Code Driver Implementation
 * Manages POST codes for simulation observability per SMC ROM Boot Architecture Specification.
 * Uses scratch register 1 (0xC0039088) for structured 32-bit POST code reporting.
 */

#include "smc_post_code.h"
#include "smc_scratchpad.h" /* For SMC_SCRATCH_SIM_POST_CODE */
#include "smc_defines.h"

/* Current POST code state (cached for efficient bit manipulation) */
static uint32_t current_post_code = 0;

/*
 * POST Code Management Implementation
 */

void smc_post_code_init(void) {
    current_post_code = 0;
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_boot_phase(uint8_t phase) {
    /* Clear bits 31:28 and set new phase */
    current_post_code = (current_post_code & POST_CODE_BOOT_PHASE_MASK) |
                        ((uint32_t)(phase & 0xF) << POST_CODE_BOOT_PHASE_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_occp_state(uint8_t state) {
    /* Clear bits 27:24 and set new state */
    current_post_code = (current_post_code & POST_CODE_OCCP_STATE_MASK) |
                        ((uint32_t)(state & 0xF) << POST_CODE_OCCP_STATE_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_interface(uint8_t interface) {
    /* Clear bits 23:20 and set new interface */
    current_post_code = (current_post_code & POST_CODE_INTERFACE_MASK) |
                        ((uint32_t)(interface & 0xF) << POST_CODE_INTERFACE_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_error(uint8_t error) {
    /* Clear bits 19:16 and set new error */
    current_post_code = (current_post_code & POST_CODE_ERROR_MASK) |
                        ((uint32_t)(error & 0xF) << POST_CODE_ERROR_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_security_decisions(uint8_t decisions) {
    /* Clear bits 15:12 and set new decisions */
    current_post_code = (current_post_code & POST_CODE_SECURITY_MASK) |
                        ((uint32_t)(decisions & 0xF) << POST_CODE_SECURITY_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_boot_mode_decisions(uint8_t decisions) {
    /* Clear bits 11:8 and set new decisions */
    current_post_code = (current_post_code & POST_CODE_BOOT_MODE_MASK) |
                        ((uint32_t)(decisions & 0xF) << POST_CODE_BOOT_MODE_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_strap_status(uint8_t straps) {
    /* Clear bits 7:4 and set new strap status */
    current_post_code = (current_post_code & POST_CODE_STRAP_STATUS_MASK) |
                        ((uint32_t)(straps & 0xF) << POST_CODE_STRAP_STATUS_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_set_coordination_state(uint8_t state) {
    /* Clear bits 3:0 and set new coordination state */
    current_post_code = (current_post_code & POST_CODE_COORD_STATE_MASK) |
                        ((uint32_t)(state & 0xF) << POST_CODE_COORD_STATE_SHIFT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_manifest_ready(void) {
    current_post_code |= (1U << POST_CODE_COORD_MANIFEST_READY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_status_buffer_ready(void) {
    current_post_code |= (1U << POST_CODE_COORD_STATUS_BUF_READY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_sep_comm_active(void) {
    current_post_code |= (1U << POST_CODE_COORD_SEP_COMM_ACTIVE_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

/*
 * Convenience Functions for Common Operations
 */

void smc_post_code_mark_primary(void) {
    current_post_code |= (1U << POST_CODE_BOOT_PRIMARY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_secondary(void) {
    current_post_code &= ~(1U << POST_CODE_BOOT_PRIMARY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_recovery_mode(void) {
    current_post_code |= (1U << POST_CODE_BOOT_RECOVERY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_i2c_boot(void) {
    current_post_code |= (1U << POST_CODE_BOOT_I2C_MODE_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_sram_auto_zero_disabled(void) {
    current_post_code |= (1U << POST_CODE_BOOT_SRAM_NO_ZERO_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_clear_sram_auto_zero_disabled(void) {
    current_post_code &= ~(1U << POST_CODE_BOOT_SRAM_NO_ZERO_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_secure_mode(void) {
    current_post_code |= (1U << POST_CODE_SEC_SECURE_MODE_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_sram_ready(void) {
    current_post_code |= (1U << POST_CODE_COORD_SRAM_READY_BIT);
    write_scratch(SMC_SCRATCH_SIM_POST_CODE, current_post_code);
}

void smc_post_code_mark_interface_ready(uint8_t interface) {
    smc_post_code_set_interface(interface);
}

void smc_post_code_mark_occp_ready(void) {
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_OCCP_READY);
}

void smc_post_code_mark_error(uint8_t error_code) {
    smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_ERROR);
    smc_post_code_set_error(error_code);
}

uint32_t smc_post_code_get_current(void) {
    return current_post_code;
}
