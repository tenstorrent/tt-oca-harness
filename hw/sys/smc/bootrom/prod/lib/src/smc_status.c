/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Status Reporting Implementation
 * Status reporting using fixed ring buffers.
 */

#include "smc_status.h"
#include "smc_scratchpad.h"
#include "smc_rom_defs.h"
#include "smc_defines.h"
#include <string.h>

/* Global status buffers (located at end of SRAM, 512 entries each) */
smc_ring_buffer_t *smc_status_buffer = (smc_ring_buffer_t *)SMC_STATUS_BUFFER_ADDR;
smc_ring_buffer_t *sep_status_buffer = (smc_ring_buffer_t *)SEP_STATUS_BUFFER_ADDR;

/* Helper to create status message */
static inline uint32_t create_status_msg(uint32_t fw_id, uint32_t msg_type, uint32_t msg_value) {
    // msg_type = 0x1 informational, 0x8 warning ,0xf error
    // fw_id = 0x01 SEP_BL0, 0x02 SEP_BL1, 0x03 SMC_BL0
    // msg_value = 16-bit value specific to msg_type
    return ((msg_type & 0xFF) << 24) | ((fw_id & 0xFF) << 16) | (msg_value & 0xFFFF);
}

/*
 * Status reporting API
 */

bool smc_status_init(void) {
    /* Initialize SMC status buffer */
    smc_ring_buffer_init(smc_status_buffer);

    /* Initialize SEP status buffer */
    smc_ring_buffer_init(sep_status_buffer);

    /* Coordinate with SEP: Set status buffer address and signal readiness */
    smc_scratchpad_set_status_buffer_offset((uint32_t)SEP_STATUS_BUFFER_ADDR);
    smc_scratchpad_signal_status_buffer_ready();

    /* Report init complete */
    smc_status_report(SMC_STATUS_TYPE_STATUS, 0x000001);

    return true;
}

void smc_status_report(uint32_t msg_type, uint32_t msg_value) {
    uint32_t message = create_status_msg(SMC_STATUS_FW_ID_SMC, msg_type, msg_value);
    smc_ring_buffer_write(smc_status_buffer, message);
}

bool smc_status_read(uint32_t *message) {
    return smc_ring_buffer_read(smc_status_buffer, message) == SMC_RING_BUFFER_OK;
}

bool sep_status_read(uint32_t *message) {
    return smc_ring_buffer_read(sep_status_buffer, message) == SMC_RING_BUFFER_OK;
}
