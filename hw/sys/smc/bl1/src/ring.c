/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Writer for the SMC status ring the SMC Boot ROM keeps at the top of SMC SRAM. The header
// lives in SRAM the SEP can reach, so it is read once and the write index is kept here: a
// corrupted header can never steer a store outside the ring.

#include <stddef.h>

#include "smc_bl1.h"
#include "smc_rom_defs.h"
#include "smc_status.h"

static volatile smc_ring_buffer_t *ring;
static uint32_t ring_head;

void smc_bl1_ring_init(void) {
    volatile smc_ring_buffer_t *rom_ring = (volatile smc_ring_buffer_t *)SMC_STATUS_BUFFER_ADDR;
    uint32_t status = (uint32_t)smc_bl1_rd64(SMU_BL1_SMC_SCRATCH(SMU_BL1_SCRATCH_STATUS_TO_SEP));

    if ((status & SMU_BL1_STATUS_BUFFER_READY) == 0u) return;
    if (rom_ring->num_entries != SMC_RING_BUFFER_SIZE) return;
    uint32_t head = rom_ring->head;
    if (head >= SMC_RING_BUFFER_SIZE) return;
    ring_head = head;
    ring = rom_ring;
}

void smc_bl1_ring_write(uint32_t word) {
    if (ring == NULL) return;
    uint32_t next = (ring_head + 1u) % SMC_RING_BUFFER_SIZE;
    uint32_t tail = ring->tail;
    // A full ring drops its oldest entry, as the ROM's writer does.
    if (next == tail) ring->tail = (tail + 1u) % SMC_RING_BUFFER_SIZE;
    ring->entries[ring_head] = word;
    ring_head = next;
    ring->head = next;
}
