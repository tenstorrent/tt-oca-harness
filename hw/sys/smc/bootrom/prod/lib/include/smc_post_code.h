/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC POST Code Driver
 * Manages POST codes for simulation observability per SMC ROM Boot Architecture Specification.
 * Uses scratch register 1 (0xC0039088) for structured 32-bit POST code reporting.
 */

#ifndef SMC_POST_CODE_H
#define SMC_POST_CODE_H

#include <stdint.h>

/*
 * POST Code Bitfield Definitions (32-bit structured format)
 * Per SMC ROM Boot Architecture Specification Section: POST Code Definition
 */

/* Boot Phase Definitions (bits 31:28) */
#define POST_CODE_BOOT_PHASE_INIT 0x0          /* Initial state after reset */
#define POST_CODE_BOOT_PHASE_STRAP_FUSE 0x1    /* Reading straps and fuses */
#define POST_CODE_BOOT_PHASE_SRAM_SETUP 0x2    /* Setting up SRAM */
#define POST_CODE_BOOT_PHASE_IFACE_CONFIG 0x3  /* Configuring interfaces */
#define POST_CODE_BOOT_PHASE_OCCP_READY 0x4    /* Ready for OCCP commands */
#define POST_CODE_BOOT_PHASE_OCCP_PROC 0x5     /* Processing OCCP commands */
#define POST_CODE_BOOT_PHASE_BOOT_COMPLETE 0x6 /* Boot sequence complete */
#define POST_CODE_BOOT_PHASE_ERROR 0x7         /* Error state encountered */

/* OCCP State Definitions (bits 27:24) */
#define POST_CODE_OCCP_STATE_IDLE 0x0         /* Idle */
#define POST_CODE_OCCP_STATE_CMD_RECEIVED 0x1 /* Command received */
#define POST_CODE_OCCP_STATE_PROCESSING 0x2   /* Processing */
#define POST_CODE_OCCP_STATE_RESP_READY 0x3   /* Response ready */
#define POST_CODE_OCCP_STATE_COMPLETE 0x4     /* Complete */
#define POST_CODE_OCCP_STATE_ERROR 0x5        /* Error */

/* Interface Status Definitions (bits 23:20) */
#define POST_CODE_IFACE_NONE 0x0 /* None */
#define POST_CODE_IFACE_I3C0 0x1 /* I3C0 */
#define POST_CODE_IFACE_I3C1 0x2 /* I3C1 */
#define POST_CODE_IFACE_I3C3 0x4 /* I3C3 */
#define POST_CODE_IFACE_I2C0 0x5 /* I2C0 */
#define POST_CODE_IFACE_I2C1 0x6 /* I2C1 */
/* Values 0x3, 0x7-0xF reserved for interfaces not configured by SMC ROM */

/* Error Code Definitions (bits 19:16) */
#define POST_CODE_ERROR_NONE 0x0             /* No Error */
#define POST_CODE_ERROR_SRAM 0x1             /* SRAM Error */
#define POST_CODE_ERROR_INTERFACE 0x2        /* Interface Error */
#define POST_CODE_ERROR_COMMAND 0x3          /* Command Error */
#define POST_CODE_ERROR_ACCESS 0x4           /* Access Error */
#define POST_CODE_ERROR_INVALID_SEC_MODE 0x5 /* Invalid Security Mode */

/* Security Decision Bits (bits 15:12) */
#define POST_CODE_SEC_SECURE_MODE_BIT 15 /* Secure Mode */
#define POST_CODE_SEC_PROD_MODE_BIT 14   /* Production Mode */
#define POST_CODE_SEC_RMA_SOP_BIT 13     /* RMA SOP Mode */

/* Boot Mode Decision Bits (bits 11:8) */
#define POST_CODE_BOOT_PRIMARY_BIT 11     /* Primary Chiplet */
#define POST_CODE_BOOT_RECOVERY_BIT 10    /* Recovery Mode */
#define POST_CODE_BOOT_I2C_MODE_BIT 9     /* I2C Mode */
#define POST_CODE_BOOT_SRAM_NO_ZERO_BIT 8 /* SRAM Auto-Zero Disabled */

/* Strap Status Bits (bits 7:4; bit 7 is reserved) */
#define POST_CODE_STRAP_STATUS_RPT_DIS_BIT 6  /* Status Report Disable */
#define POST_CODE_STRAP_SRAM_REPAIR_BYP_BIT 5 /* SRAM Repair Bypass */

/* Coordination State Bits (bits 3:0) */
#define POST_CODE_COORD_SRAM_READY_BIT 3       /* SRAM Ready */
#define POST_CODE_COORD_MANIFEST_READY_BIT 2   /* Manifest Ready */
#define POST_CODE_COORD_STATUS_BUF_READY_BIT 1 /* Status Buffer Ready */
#define POST_CODE_COORD_SEP_COMM_ACTIVE_BIT 0  /* SEP Communication Active */

/* Bit Field Shift and Mask Constants for Implementation */
#define POST_CODE_BOOT_PHASE_SHIFT 28
#define POST_CODE_BOOT_PHASE_MASK 0x0FFFFFFF

#define POST_CODE_OCCP_STATE_SHIFT 24
#define POST_CODE_OCCP_STATE_MASK 0xF0FFFFFF

#define POST_CODE_INTERFACE_SHIFT 20
#define POST_CODE_INTERFACE_MASK 0xFF0FFFFF

#define POST_CODE_ERROR_SHIFT 16
#define POST_CODE_ERROR_MASK 0xFFF0FFFF

#define POST_CODE_SECURITY_SHIFT 12
#define POST_CODE_SECURITY_MASK 0xFFFF0FFF

#define POST_CODE_BOOT_MODE_SHIFT 8
#define POST_CODE_BOOT_MODE_MASK 0xFFFFF0FF

#define POST_CODE_STRAP_STATUS_SHIFT 4
#define POST_CODE_STRAP_STATUS_MASK 0xFFFFFF0F

#define POST_CODE_COORD_STATE_SHIFT 0
#define POST_CODE_COORD_STATE_MASK 0xFFFFFFF0

/*
 * POST Code Management API
 */

/**
 * Initialize POST code system
 * Sets initial state (0x00000000)
 */
void smc_post_code_init(void);

/**
 * Update boot phase (bits 31:28)
 * @param phase Boot phase value (0x0-0xF)
 */
void smc_post_code_set_boot_phase(uint8_t phase);

/**
 * Update OCCP state (bits 27:24)
 * @param state OCCP state value (0x0-0xF)
 */
void smc_post_code_set_occp_state(uint8_t state);

/**
 * Update interface status (bits 23:20)
 * @param interface Interface value (0x0-0xF)
 */
void smc_post_code_set_interface(uint8_t interface);

/**
 * Set error code (bits 19:16)
 * @param error Error code value (0x0-0xF)
 */
void smc_post_code_set_error(uint8_t error);

/**
 * Update security decisions (bits 15:12)
 * @param decisions Security decision bitfield
 */
void smc_post_code_set_security_decisions(uint8_t decisions);

/**
 * Update boot mode decisions (bits 11:8)
 * @param decisions Boot mode decision bitfield
 */
void smc_post_code_set_boot_mode_decisions(uint8_t decisions);

/**
 * Update strap status (bits 7:4)
 * @param straps Strap status bitfield
 */
void smc_post_code_set_strap_status(uint8_t straps);

/**
 * Update coordination state (bits 3:0)
 * @param state Coordination state bitfield
 */
void smc_post_code_set_coordination_state(uint8_t state);

/*
 * Convenience Functions for Common Operations
 */

/**
 * Mark chiplet as primary
 */
void smc_post_code_mark_primary(void);

/**
 * Mark chiplet as secondary
 */
void smc_post_code_mark_secondary(void);

/**
 * Mark recovery mode enabled
 */
void smc_post_code_mark_recovery_mode(void);
/**
 * I2C boot mode enabled
 */
void smc_post_code_mark_i2c_boot(void);

/**
 * Mark manifest ready
 */
void smc_post_code_mark_manifest_ready(void);
/**
 * Mark status buffer ready
 */
void smc_post_code_mark_status_buffer_ready(void);
/**
 * Mark SEP communication active
 */
void smc_post_code_mark_sep_comm_active(void);
/**
 * Mark SRAM auto-zero disabled via strap
 */
void smc_post_code_mark_sram_auto_zero_disabled(void);
/**
 * Clear SRAM auto-zero disabled strap indication
 */
void smc_post_code_clear_sram_auto_zero_disabled(void);

/**
 * Mark secure mode enabled
 */
void smc_post_code_mark_secure_mode(void);

/**
 * Mark SRAM as ready
 */
void smc_post_code_mark_sram_ready(void);

/**
 * Mark interface as ready
 * @param interface Interface identifier
 */
void smc_post_code_mark_interface_ready(uint8_t interface);

/**
 * Mark OCCP as ready
 */
void smc_post_code_mark_occp_ready(void);

/**
 * Mark error state
 * @param error_code Error code to set
 */
void smc_post_code_mark_error(uint8_t error_code);

/**
 * Get current POST code value
 * @return Current 32-bit POST code
 */
uint32_t smc_post_code_get_current(void);

#endif /* SMC_POST_CODE_H */
