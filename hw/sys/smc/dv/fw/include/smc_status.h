/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Status Reporting
 * Status reporting using fixed ring buffers in SRAM.
 */

#ifndef SMC_STATUS_H
#define SMC_STATUS_H

#include <stdint.h>
#include <stdbool.h>
#include "smc_ring_buffer.h"

/* Status message format (32-bit)
 * [31:24] - Message Type (0x1: status, 0x8: warning, 0xF: error)
 * [23:16] - Firmware ID (0x1 = SEP BL0, 0x2 = SEP BL1, 0x3 = SMC BL0, etc). (0x0 skipped to avoid 0
 * values being valid.) [15:0]  - Message Value
 */

/* Firmware ID definitions */
#define SMC_STATUS_FW_ID_SEP_BL0 0x1
#define SMC_STATUS_FW_ID_SEP_BL1 0x2
#define SMC_STATUS_FW_ID_SMC_BL0 0x3
#define SMC_STATUS_FW_ID_SMC_BL1 0x4

/* Message type definitions */
#define SMC_STATUS_TYPE_STATUS 0x1
#define SMC_STATUS_TYPE_WARNING 0x8
#define SMC_STATUS_TYPE_ERROR 0xF
/* Reserved message types: 0x0 to 0x7F */
/* Custom message types: 0x80 to 0xFF */

/*
 * Memory locations in SRAM - Ring buffers at end of memory for natural protection
 */
#define SMC_SRAM_END (SMC_SRAM_BASE + SMC_SRAM_SIZE)

/* Ring buffers at the very end of SRAM */
#define SEP_STATUS_BUFFER_ADDR (SMC_SRAM_END - sizeof(smc_ring_buffer_t)) /* Last 512 bytes */
#define SMC_STATUS_BUFFER_ADDR \
    (SEP_STATUS_BUFFER_ADDR - sizeof(smc_ring_buffer_t)) /* Before SEP buffer */

/*
 * Global status buffers
 */
extern smc_ring_buffer_t *smc_status_buffer;
extern smc_ring_buffer_t *sep_status_buffer;

/*
 * Status reporting API
 */

/**
 * Initialize status reporting system
 */
bool smc_status_init(void);

/**
 * Report SMC status message
 */
void smc_status_report(uint32_t msg_type, uint32_t msg_value);

/**
 * Read SMC status message
 */
bool smc_status_read(uint32_t *message);

/**
 * Read SEP status message
 */
bool sep_status_read(uint32_t *message);

#endif /* SMC_STATUS_H */
