/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Status ring buffer implementation.
//
// Implements a lock-free ring buffer in SMC SRAM for SEP → SMC status
// reporting.  SEP owns the head pointer; SMC owns the tail pointer.
//
// Implements a lock-free ring buffer in SMC SRAM for SEP → SMC status
// reporting.  SEP owns the head pointer; SMC owns the tail pointer.

#include <stdint.h>
#include <stdbool.h>

#include "errors.h"
#include "status_ring.h"
#include "sep_smc_interface.h"
#include "rom_virt_console.h"

#define MIN_WARNING_CAPACITY 2
#define MIN_STATUS_CAPACITY 3

/*
 * Status reporting structure that exists in SMC SRAM
 */
struct status_ring_buffer {
    uint32_t head; /* SEP modified */
    uint32_t tail; /* SMC modified */
    uint32_t num_entries;
    uint32_t entries[];
};

static bool rpt_status_enabled = false;
static volatile struct status_ring_buffer *ring_buffer;

static inline int contains_range_u32(uint32_t base, uint32_t size, uint32_t addr, uint32_t len) {
    return (addr >= base) && (len <= size) && ((addr - base) <= (size - len));
}

void init_status_reporting(void) {
    /*
     * wait for status reporting fifo to be ready
     * potentially hang forever
     */
    while (!(smc_scratch_read(SMC_SCRATCH_STATUS_TO_SEP_IDX) & SMC_SEP_STATUS_BUFFER_READY))
        ;

    STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_STATUS_REPORTING_READY));

    uint32_t offset = smc_scratch_read(SMC_SCRATCH_STATUS_BUFFER_ADDR_IDX);

    uint32_t smc_sram = sep_get_smc_sram_base();

    // Validate that the offset of the ring buffer structure is within SMC SRAM.
    // Writes to entries are validated on every write.
    if (!contains_range_u32(0, SMC_SRAM_SIZE_BYTES, offset, sizeof(struct status_ring_buffer))) {
        STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_ERROR, SEP_MSG_STATUS_REPORTING_INVALID));
        return;
    }

    ring_buffer = (volatile struct status_ring_buffer *)(smc_sram + offset);
    rpt_status_enabled = true;

    simputshex32("ring buffer address: ", (uint32_t)ring_buffer);
    simputshex32("ring buffer head: ", ring_buffer->head);
    simputshex32("ring buffer tail: ", ring_buffer->tail);
    simputshex32("ring buffer num_entries: ", ring_buffer->num_entries);
}

void status_ring_buffer_insert(uint32_t value) {
    uint32_t head, tail, used, capacity, num_entries;
    uint32_t type = (value & 0xff000000) >> 24; // Extract bits [31:24] - Message Type
    volatile uint32_t *entries;

    if (!rpt_status_enabled) return;

    // Snapshot ring buffer values before checks
    head = ring_buffer->head;
    tail = ring_buffer->tail;
    entries = ring_buffer->entries;
    num_entries = ring_buffer->num_entries;

    used = (head >= tail) ? head - tail : num_entries - tail + head;
    capacity = num_entries - used - 1;

    uint32_t smc_sram = sep_get_smc_sram_base();

    // Invalid ring buffer state. Report an error to the scratch register.
    // If the head points outside of SMC SRAM something has gone wrong.
    // Don't write to an unknown address.
    // Don't disable status reporting, in case it's a transient error.
    if (num_entries == 0 || head >= num_entries || tail >= num_entries || capacity >= num_entries ||
        !contains_range_u32(smc_sram, SMC_SRAM_SIZE_BYTES, (uint32_t)(entries + head),
                            sizeof(uint32_t))) {
        STATUS_OUT(STATUS_ENCODE(STATUS_TYPE_ERROR, SEP_MSG_STATUS_REPORTING_INVALID));
        return;
    }

    /* if no entry left, we can't do anything so return */
    if (!capacity) return;

    /*
     * Check capacity against type specific constraints
     * Warnings require 2 entries, 1 for the warning and another for an error
     * Status require 3 entries.  Room is saved for a warning and an error
     *
     * If enough room exists for only 1 warning or status, log an overflow
     * instead to denote the FIFO filling up for that message type
     */
    if (type == STATUS_TYPE_WARN) {
        /* this is for warning messages */
        if (capacity < MIN_WARNING_CAPACITY)
            return;
        else if (capacity == MIN_WARNING_CAPACITY)
            value = STATUS_ENCODE(STATUS_TYPE_WARN, SEP_MSG_WARNING_OVERFLOW);
    } else if (type != STATUS_TYPE_ERROR) {
        /* this is for any status messages */
        if (capacity < MIN_STATUS_CAPACITY)
            return;
        else if (capacity == MIN_STATUS_CAPACITY)
            value = STATUS_ENCODE(STATUS_TYPE_INFO, SEP_MSG_INFO_OVERFLOW);
    }

    entries[head] = value;
    head++;
    if (head >= num_entries) {
        head = 0;
    }
    ring_buffer->head = head;
}
