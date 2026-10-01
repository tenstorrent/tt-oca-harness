/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC OCCP Error Code Definitions
 * Status reporting codes for OCCP command processing and boot sequence
 *
 *
 * This header defines all error and status codes used by the SMC production
 * ROM FW for ring buffer status reporting. See
 * hw/sys/smc/bootrom/prod/doc/status-coordination.adoc for the documented
 * values and current emission behavior.
 */

#ifndef SMC_OCCP_ERROR_CODES_H
#define SMC_OCCP_ERROR_CODES_H

/*********************************************************************
 * Boot Sequence Status Codes (0x010-0x05F)
 ********************************************************************/
#define SMC_STATUS_ROM_STARTED 0x001 /* ROM started */
#define SMC_STATUS_BOOT_START \
    0x010 /* Boot sequence started / Config read (OR with strap status) \
           */
/*Removing SMC_STATUS_CONFIG_LOADED, there is no configuration to be loaded for SMC ROM*/
#define SMC_STATUS_RECOVERY_MODE 0x020       /* Recovery mode detected */
#define SMC_STATUS_PRIMARY_MODE 0x021        /* Primary mode detected */
#define SMC_STATUS_SECONDARY_MODE 0x022      /* Secondary mode detected */
#define SMC_STATUS_INVALID_SEC_MODE 0x025    /* Invalid security/lifecycle mode detected */
#define SMC_STATUS_OCCP_INIT_FAILED 0x030    /* OCCP initialization failed */
#define SMC_STATUS_OCCP_READY 0x031          /* OCCP ready and operational */
#define SMC_STATUS_COORDINATION_ACTIVE 0x040 /* Coordination active */
#define SMC_STATUS_BOOT_COMPLETE 0x050       /* Boot sequence completed successfully */
#define SMC_STATUS_UNEXPECTED_EXIT 0x0FF     /* Unexpected exit from main loop */

/*********************************************************************
 * OCCP Command Processing Error Codes (0x100-0x1FF)
 ********************************************************************/

/* Bus/Command Errors (0x100-0x11F) */
#define SMC_OCCP_ERROR_CMD_READ 0x100    /* Command read error from bus */
#define SMC_OCCP_ERROR_CMD_UNKNOWN 0x101 /* Unknown command (OR with command word in low byte) */
#define SMC_OCCP_ERROR_CMD_FAILED \
    0x110 /* Command execution failed (OR with error code in low nibble) */
#define SMC_OCCP_ERROR_CMD_READ 0x100    /* Command read error from bus */
#define SMC_OCCP_ERROR_CMD_UNKNOWN 0x101 /* Unknown command (OR with command word in low byte) */
#define SMC_OCCP_ERROR_CMD_FAILED \
    0x110 /* Command execution failed (OR with error code in low nibble) */

/* READ Command Errors (0x120-0x12F) */
#define SMC_OCCP_ERROR_READ_OVERFLOW 0x120 /* READ buffer overflow (size exceeds maximum) */
#define SMC_OCCP_ERROR_READ_ACCESS_DENIED \
    0x121 /* READ access denied (OR with access violation code in upper nibble) */
#define SMC_OCCP_ERROR_READ_OVERFLOW 0x120 /* READ buffer overflow (size exceeds maximum) */
#define SMC_OCCP_ERROR_READ_ACCESS_DENIED \
    0x121 /* READ access denied (OR with access violation code in upper nibble) */

/* WRITE Command Errors (0x130-0x13F) */
#define SMC_OCCP_ERROR_WRITE_OVERFLOW 0x130 /* WRITE buffer overflow (size exceeds maximum) */
#define SMC_OCCP_ERROR_WRITE_ACCESS_DENIED \
    0x131 /* WRITE access denied (OR with access violation code in upper nibble) */
#define SMC_OCCP_ERROR_WRITE_OVERFLOW 0x130 /* WRITE buffer overflow (size exceeds maximum) */
#define SMC_OCCP_ERROR_WRITE_ACCESS_DENIED \
    0x131 /* WRITE access denied (OR with access violation code in upper nibble) */

/* Security Violation Errors (0x140-0x14F) */
#define SMC_OCCP_ERROR_VALIDATE_SECURITY 0x140 /* VALIDATE_BOOT command access validation error */
#define SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED \
    0x141                                      /* VALIDATE_BOOT command address validation error */
#define SMC_OCCP_ERROR_VALIDATE_SECURITY 0x140 /* VALIDATE_BOOT command access validation error */
#define SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED \
    0x141 /* VALIDATE_BOOT command address validation error */

/*********************************************************************
 * OCCP JUMP Command Codes (0x200-0x20F)
 ********************************************************************/
#define SMC_OCCP_STATUS_JUMP_EXECUTED \
    0x200 /* JUMP executed (OR with address bits [23:16] in low byte) */
#define SMC_OCCP_ERROR_JUMP_SECURITY 0x201    /* JUMP blocked due to security violation */
#define SMC_OCCP_ERROR_JUMP_READ_FAILED 0x202 /* JUMP failed due to read error */
#define SMC_OCCP_STATUS_JUMP_EXECUTED \
    0x200 /* JUMP executed (OR with address bits [23:16] in low byte) */
#define SMC_OCCP_ERROR_JUMP_SECURITY 0x201    /* JUMP blocked due to security violation */
#define SMC_OCCP_ERROR_JUMP_READ_FAILED 0x202 /* JUMP failed due to read error */

/*********************************************************************
 * Helper Macros for Error Code Construction
 ********************************************************************/

/* Macro to combine error code with additional data */
#define SMC_OCCP_ERROR_WITH_DATA(base_code, data) ((base_code) | ((data)&0xFF))

/* Macro to combine error code with nibble data in upper nibble */
#define SMC_OCCP_ERROR_WITH_NIBBLE(base_code, nibble) ((base_code) | (((nibble)&0xF) << 8))

/* Macro to extract base error code (clear additional data) */
#define SMC_OCCP_ERROR_BASE(error_code) ((error_code)&0xFF0)

/* Macro to extract additional data from error code */
#define SMC_OCCP_ERROR_DATA(error_code) ((error_code)&0xFF)

#endif /* SMC_OCCP_ERROR_CODES_H */
