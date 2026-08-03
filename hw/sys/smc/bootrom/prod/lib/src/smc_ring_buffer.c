/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Ring Buffer Implementation
 * Fixed-size ring buffer for status messages.
 */

#include "smc_ring_buffer.h"
#include <string.h>

void smc_ring_buffer_init(smc_ring_buffer_t *buffer) {
    if (!buffer) return;

    buffer->head = 0;
    buffer->tail = 0;
    buffer->num_entries = SMC_RING_BUFFER_SIZE;
    memset(buffer->entries, 0, sizeof(buffer->entries));
}

smc_ring_buffer_result_t smc_ring_buffer_write(smc_ring_buffer_t *buffer, uint32_t entry) {
    if (!buffer) return SMC_RING_BUFFER_EMPTY;

    uint32_t next_head = (buffer->head + 1) % SMC_RING_BUFFER_SIZE;

    /* If buffer is full, overwrite oldest entry */
    if (next_head == buffer->tail) {
        buffer->tail = (buffer->tail + 1) % SMC_RING_BUFFER_SIZE;
    }

    buffer->entries[buffer->head] = entry;
    buffer->head = next_head;

    return SMC_RING_BUFFER_OK;
}

smc_ring_buffer_result_t smc_ring_buffer_read(smc_ring_buffer_t *buffer, uint32_t *entry) {
    if (!buffer || !entry) return SMC_RING_BUFFER_EMPTY;

    if (buffer->head == buffer->tail) {
        return SMC_RING_BUFFER_EMPTY;
    }

    *entry = buffer->entries[buffer->tail];
    buffer->tail = (buffer->tail + 1) % SMC_RING_BUFFER_SIZE;

    return SMC_RING_BUFFER_OK;
}

bool smc_ring_buffer_is_empty(const smc_ring_buffer_t *buffer) {
    if (!buffer) return true;
    return buffer->head == buffer->tail;
}

bool smc_ring_buffer_is_full(const smc_ring_buffer_t *buffer) {
    if (!buffer) return false;
    return ((buffer->head + 1) % SMC_RING_BUFFER_SIZE) == buffer->tail;
}

uint32_t smc_ring_buffer_count(const smc_ring_buffer_t *buffer) {
    if (!buffer) return 0;

    if (buffer->head >= buffer->tail) {
        return buffer->head - buffer->tail;
    } else {
        return SMC_RING_BUFFER_SIZE - buffer->tail + buffer->head;
    }
}

uint32_t smc_ring_buffer_capacity(const smc_ring_buffer_t *buffer) {
    if (!buffer) return 0;
    return buffer->num_entries;
}
