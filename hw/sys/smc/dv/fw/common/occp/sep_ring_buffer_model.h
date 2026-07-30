/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SEP_RING_BUFFER_MODEL_H
#define SEP_RING_BUFFER_MODEL_H

#include <stdbool.h>
#include <stdint.h>

#include "smc_defines.h"

#define SEP_RING_BUFFER_SHADOW_ADDR ((uintptr_t)0xC015B000)
#define SEP_RING_BUFFER_GUARD_SCRATCH 13
#define SEP_RING_BUFFER_MODEL_SIZE 512

typedef struct {
    uint32_t head;
    uint32_t tail;
    uint32_t entries[SEP_RING_BUFFER_MODEL_SIZE];
} sep_ring_buffer_shadow_t;

typedef struct {
    volatile sep_ring_buffer_shadow_t *shadow;
} sep_ring_buffer_model_t;

void sep_ring_buffer_model_init(sep_ring_buffer_model_t *model);
bool sep_ring_buffer_model_empty(const sep_ring_buffer_model_t *model);
uint32_t sep_ring_buffer_model_peek(const sep_ring_buffer_model_t *model);
void sep_ring_buffer_model_pop(sep_ring_buffer_model_t *model);

static inline void sep_ring_buffer_guard_set(void) {
    write_scratch(SEP_RING_BUFFER_GUARD_SCRATCH, 1);
}

static inline void sep_ring_buffer_guard_clear(void) {
    write_scratch(SEP_RING_BUFFER_GUARD_SCRATCH, 0);
}

#endif /* SEP_RING_BUFFER_MODEL_H */
