/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "sep_ring_buffer_model.h"

static volatile sep_ring_buffer_shadow_t *get_shadow(const sep_ring_buffer_model_t *model) {
    volatile sep_ring_buffer_shadow_t *shadow = NULL;
    if (model != NULL) {
        shadow = model->shadow;
    }

    if (shadow == NULL) {
        shadow = (volatile sep_ring_buffer_shadow_t *)(SEP_RING_BUFFER_SHADOW_ADDR);
    }
    return shadow;
}

void sep_ring_buffer_model_init(sep_ring_buffer_model_t *model) {
    if (model == NULL) {
        return;
    }

    model->shadow = (volatile sep_ring_buffer_shadow_t *)(SEP_RING_BUFFER_SHADOW_ADDR);
}

bool sep_ring_buffer_model_empty(const sep_ring_buffer_model_t *model) {
    volatile sep_ring_buffer_shadow_t *shadow = get_shadow(model);
    return (shadow->head % SEP_RING_BUFFER_MODEL_SIZE) ==
           (shadow->tail % SEP_RING_BUFFER_MODEL_SIZE);
}

uint32_t sep_ring_buffer_model_peek(const sep_ring_buffer_model_t *model) {
    volatile sep_ring_buffer_shadow_t *shadow = get_shadow(model);
    uint32_t tail = shadow->tail % SEP_RING_BUFFER_MODEL_SIZE;
    return shadow->entries[tail];
}

void sep_ring_buffer_model_pop(sep_ring_buffer_model_t *model) {
    volatile sep_ring_buffer_shadow_t *shadow = get_shadow(model);
    uint32_t tail = shadow->tail % SEP_RING_BUFFER_MODEL_SIZE;
    tail = (tail + 1) % SEP_RING_BUFFER_MODEL_SIZE;
    shadow->tail = tail;
}
