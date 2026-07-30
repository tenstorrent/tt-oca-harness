/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC OCCP Status Register
 * OCCP status register management per SMC ROM Boot Architecture Specification.
 */

#ifndef SMC_OCCP_STATUS_H
#define SMC_OCCP_STATUS_H

#include <stdint.h>
#include <stdbool.h>

/*
 * OCCP Status Register Format (32-bit)
 * [31:24] - Reserved (future use)
 * [23:16] - Error Code (last error encountered)
 * [15:8]  - Command Count (number of commands processed, wraps at 255)
 * [7:4]   - Interface Status (I2C/I3C state)
 * [3:0]   - Boot Status (current boot phase)
 */

/* OCCP Status Register Bitfield Definitions */
#define OCCP_STATUS_BOOT_STATUS_SHIFT 0
#define OCCP_STATUS_BOOT_STATUS_MASK 0x0F
#define OCCP_STATUS_INTERFACE_SHIFT 4
#define OCCP_STATUS_INTERFACE_MASK 0xF0
#define OCCP_STATUS_CMD_COUNT_SHIFT 8
#define OCCP_STATUS_CMD_COUNT_MASK 0xFF00
#define OCCP_STATUS_ERROR_CODE_SHIFT 16
#define OCCP_STATUS_ERROR_CODE_MASK 0xFF0000
#define OCCP_STATUS_RESERVED_SHIFT 24
#define OCCP_STATUS_RESERVED_MASK 0xFF000000

/* Boot Status Values */
typedef enum {
    OCCP_BOOT_STATUS_INIT = 0x0,            /* Hardware initialization */
    OCCP_BOOT_STATUS_STRAP_READ = 0x1,      /* Reading straps and fuses */
    OCCP_BOOT_STATUS_INTERFACE_SETUP = 0x2, /* Setting up I2C/I3C interface */
    OCCP_BOOT_STATUS_READY = 0x3,           /* Ready for OCCP commands */
    OCCP_BOOT_STATUS_PROCESSING = 0x4,      /* Processing OCCP command */
    OCCP_BOOT_STATUS_COMPLETE = 0x5,        /* Boot sequence complete */
    OCCP_BOOT_STATUS_ERROR = 0xF            /* Boot error state */
} occp_boot_status_t;

/* Interface Status Values */
typedef enum {
    OCCP_INTERFACE_STATUS_DISABLED = 0x0, /* Interface disabled */
    OCCP_INTERFACE_STATUS_READY = 0x1,    /* I2C/I3C ready */
    OCCP_INTERFACE_STATUS_ERROR = 0xF     /* Interface error */
} occp_interface_status_t;

/* Error Code Values */
typedef enum {
    OCCP_ERROR_NONE = 0x00,                 /* No error */
    OCCP_ERROR_INVALID_COMMAND = 0x01,      /* Invalid command received */
    OCCP_ERROR_ACCESS_VIOLATION = 0x02,     /* Memory access violation */
    OCCP_ERROR_ALIGNMENT_ERROR = 0x03,      /* Address alignment error */
    OCCP_ERROR_INTERFACE_ERROR = 0x04,      /* I2C/I3C interface error */
    OCCP_ERROR_SECURITY_VIOLATION = 0x05,   /* Security policy violation */
    OCCP_ERROR_BUFFER_OVERFLOW = 0x06,      /* Command buffer overflow */
    OCCP_ERROR_TIMEOUT = 0x07,              /* Command timeout */
    OCCP_ERROR_CRC = 0x08,                  /* CRC check failure */
    OCCP_ERROR_TRANSPORT_INCOMPLETE = 0x09, /* Transport layer error */
    OCCP_ERROR_TRANSPORT_OVERFLOW = 0x0A,   /* Transport layer error */
    OCCP_ERROR_GENERAL = 0xFF               /* General error */
} occp_error_code_t;

/*
 * OCCP Status API
 */

/**
 * Initialize OCCP status register
 */
void occp_status_init(void);

/**
 * @return 32-bit OCCP status register value
 */
uint32_t occp_status_get(void);

/**
 * Set boot status
 * @param status Boot status value
 */
void occp_status_set_boot_status(occp_boot_status_t status);

/**
 * Get current boot status
 * @return Current boot status
 */
occp_boot_status_t occp_status_get_boot_status(void);

/**
 * Set interface status
 * @param status Interface status value
 */
void occp_status_set_interface_status(occp_interface_status_t status);

/**
 * Get current interface status
 * @return Current interface status
 */
occp_interface_status_t occp_status_get_interface_status(void);

/**
 * Set error code
 * @param error Error code value
 */
void occp_status_set_error_code(occp_error_code_t error);

/**
 * Get current error code
 * @return Current error code
 */
occp_error_code_t occp_status_get_error_code(void);

/**
 * Increment command count (wraps at 255)
 */
void occp_status_increment_command_count(void);

/**
 * Get current command count
 * @return Current command count (0-255)
 */
uint8_t occp_status_get_command_count(void);

/**
 * Clear error code (set to OCCP_ERROR_NONE)
 */
void occp_status_clear_error(void);

/**
 * Reset command count to 0
 */
void occp_status_reset_command_count(void);

#endif /* SMC_OCCP_STATUS_H */
