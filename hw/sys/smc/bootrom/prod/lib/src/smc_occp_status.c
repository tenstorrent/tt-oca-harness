/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC OCCP Status Register Implementation
 * OCCP status register management following SMC ROM Boot Architecture Specification.
 */

#include "smc_occp_status.h"
#include <string.h>

/* Global OCCP status register */
static volatile uint32_t occp_status_register = 0;

/*
 * Internal helper functions
 */

static inline void occp_status_update_field(uint32_t mask, uint32_t shift, uint32_t value) {
    occp_status_register = (occp_status_register & ~mask) | ((value << shift) & mask);
}

static inline uint32_t occp_status_get_field(uint32_t mask, uint32_t shift) {
    return (occp_status_register & mask) >> shift;
}

/*
 * OCCP Status API Implementation
 */

void occp_status_init(void) {
    /* Initialize OCCP status register to known state */
    occp_status_register = 0;

    /* Set initial boot status */
    occp_status_set_boot_status(OCCP_BOOT_STATUS_INIT);

    /* Set initial interface status */
    occp_status_set_interface_status(OCCP_INTERFACE_STATUS_DISABLED);

    /* Clear error code */
    occp_status_set_error_code(OCCP_ERROR_NONE);

    /* Reset command count */
    occp_status_reset_command_count();
}

uint32_t occp_status_get(void) {
    return occp_status_register;
}

void occp_status_set_boot_status(occp_boot_status_t status) {
    occp_status_update_field(OCCP_STATUS_BOOT_STATUS_MASK, OCCP_STATUS_BOOT_STATUS_SHIFT,
                             (uint32_t)status);
}

occp_boot_status_t occp_status_get_boot_status(void) {
    return (occp_boot_status_t)occp_status_get_field(OCCP_STATUS_BOOT_STATUS_MASK,
                                                     OCCP_STATUS_BOOT_STATUS_SHIFT);
}

void occp_status_set_interface_status(occp_interface_status_t status) {
    occp_status_update_field(OCCP_STATUS_INTERFACE_MASK, OCCP_STATUS_INTERFACE_SHIFT,
                             (uint32_t)status);
}

occp_interface_status_t occp_status_get_interface_status(void) {
    return (occp_interface_status_t)occp_status_get_field(OCCP_STATUS_INTERFACE_MASK,
                                                          OCCP_STATUS_INTERFACE_SHIFT);
}

void occp_status_set_error_code(occp_error_code_t error) {
    occp_status_update_field(OCCP_STATUS_ERROR_CODE_MASK, OCCP_STATUS_ERROR_CODE_SHIFT,
                             (uint32_t)error);
}

occp_error_code_t occp_status_get_error_code(void) {
    return (occp_error_code_t)occp_status_get_field(OCCP_STATUS_ERROR_CODE_MASK,
                                                    OCCP_STATUS_ERROR_CODE_SHIFT);
}

void occp_status_increment_command_count(void) {
    uint8_t current_count = occp_status_get_command_count();
    uint8_t new_count = (current_count + 1) & 0xFF; /* Wrap at 255 */

    occp_status_update_field(OCCP_STATUS_CMD_COUNT_MASK, OCCP_STATUS_CMD_COUNT_SHIFT,
                             (uint32_t)new_count);
}

uint8_t occp_status_get_command_count(void) {
    return (uint8_t)occp_status_get_field(OCCP_STATUS_CMD_COUNT_MASK, OCCP_STATUS_CMD_COUNT_SHIFT);
}

void occp_status_clear_error(void) {
    occp_status_set_error_code(OCCP_ERROR_NONE);
}

void occp_status_reset_command_count(void) {
    occp_status_update_field(OCCP_STATUS_CMD_COUNT_MASK, OCCP_STATUS_CMD_COUNT_SHIFT, 0);
}
