/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Ring Buffer
 * Fixed-size ring buffer for status message storage.
 */

#ifndef SMC_RING_BUFFER_H
#define SMC_RING_BUFFER_H

#include <stdint.h>
#include <stdbool.h>

/* Ring Buffer Configuration - Compile Time Constants */
#define SMC_RING_BUFFER_SIZE 512 /* Number of entries */

/* Result codes */
typedef enum {
    SMC_RING_BUFFER_OK = 0,
    SMC_RING_BUFFER_FULL,
    SMC_RING_BUFFER_EMPTY
} smc_ring_buffer_result_t;

/* Simple ring buffer structure */
typedef struct {
    uint32_t head;                          /* Write index */
    uint32_t tail;                          /* Read index */
    uint32_t num_entries;                   /* Number of entries (hardcoded to ring buffer size) */
    uint32_t entries[SMC_RING_BUFFER_SIZE]; /* Data storage */
} smc_ring_buffer_t;

/* Ring buffer API */

/* Initialize ring buffer */
void smc_ring_buffer_init(smc_ring_buffer_t *buffer);

/* Write entry to ring buffer - overwrites oldest entry if full */
smc_ring_buffer_result_t smc_ring_buffer_write(smc_ring_buffer_t *buffer, uint32_t entry);

/* Read entry from ring buffer */
smc_ring_buffer_result_t smc_ring_buffer_read(smc_ring_buffer_t *buffer, uint32_t *entry);

/* Check if buffer is empty */
bool smc_ring_buffer_is_empty(const smc_ring_buffer_t *buffer);

/* Check if buffer is full */
bool smc_ring_buffer_is_full(const smc_ring_buffer_t *buffer);

/* Get number of used entries */
uint32_t smc_ring_buffer_count(const smc_ring_buffer_t *buffer);

/* Get ring buffer capacity (number of entries) */
uint32_t smc_ring_buffer_capacity(const smc_ring_buffer_t *buffer);

#endif /* SMC_RING_BUFFER_H */
