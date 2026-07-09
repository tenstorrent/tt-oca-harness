/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msgbuf.c
 * @brief Linear message buffer implementation (single frame only)
 *
 * Each frame starts at buffer index 0.  No wrap-around; when a frame is
 * consumed, the next frame starts at 0 again.
 */

#include "rom_msgbuf.h"
#include "rom_defs.h"

/*===========================================================================
 * Initialization
 *===========================================================================*/

/**
 * @brief Initialize a message buffer to empty state.
 *
 * @param[in,out] buf Buffer to initialize.
 */
void rom_msgbuf_init(rom_km_msgbuf_t *buf) {
    buf->count = 0;
    buf->has_frame = 0;
    buf->frame_len = 0;
    buf->tail = 0;
    buf->partial_active = 0;
}

/*===========================================================================
 * Write Path
 *===========================================================================*/

/**
 * @brief Append one word to the buffer, optionally ending the frame.
 *
 * Writes at index count; each new frame starts at 0 after the previous
 * frame is consumed.
 *
 * @param[in,out] buf       Buffer.
 * @param[in]     word      Word to append.
 * @param[in]     separator Non-zero if this word ends the frame.
 * @return 0 on success, -1 if buffer full or frame already present.
 */
int rom_msgbuf_write_word(rom_km_msgbuf_t *buf, uint32_t word, uint8_t separator) {
    if (buf->has_frame) return -1;
    if (buf->count >= ROM_KM_MSGBUF_SIZE) return -1;

    buf->data[buf->count] = word;
    buf->partial_active = 1;
    buf->count++;

    if (separator) {
        buf->frame_len = buf->count;
        buf->has_frame = 1;
        buf->partial_active = 0;
    }

    return 0;
}

/*===========================================================================
 * Read Path
 *===========================================================================*/

/**
 * @brief Peek at one word from the buffer without consuming it.
 *
 * Returns the current tail word without advancing the frame state.
 *
 * @param[in] buf  Buffer.
 * @param[out]    word Receives the word.
 * @return 0 on success, -1 if buffer empty.
 */
int rom_msgbuf_peek_word(const rom_km_msgbuf_t *buf, uint32_t *word) {
    if (!buf->has_frame || buf->tail >= buf->frame_len) return -1;

    *word = buf->data[buf->tail];
    return 0;
}

/**
 * @brief Pop one word from the buffer.
 *
 * Advances the current frame tail. Popping the last word leaves the frame
 * present but exhausted; callers must explicitly consume it once processing
 * completes.
 *
 * @param[in,out] buf  Buffer.
 * @param[out]    word Receives the word.
 * @return 0 on success, -1 if buffer empty or already exhausted.
 */
int rom_msgbuf_pop_word(rom_km_msgbuf_t *buf, uint32_t *word) {
    if (rom_msgbuf_peek_word(buf, word) != 0) return -1;

    buf->tail++;

    return 0;
}

/**
 * @brief Peek at the current frame without consuming it.
 *
 * Returns the next read index (tail) and the remaining word count so
 * callers can drain the frame in chunks.
 *
 * @param[in]  buf    Buffer.
 * @param[out] start  Receives next read index (tail).
 * @param[out] length Receives remaining words (frame_len - tail).
 * @return 0 on success, -1 if no frame available.
 */
int rom_msgbuf_peek_frame(const rom_km_msgbuf_t *buf, uint16_t *start, uint16_t *length) {
    if (!buf->has_frame) return -1;

    *start = buf->tail;
    *length = (uint16_t)(buf->frame_len - buf->tail);
    return 0;
}

/**
 * @brief Consume the current frame.
 *
 * Resets state so the next frame will start at index 0.
 *
 * @param[in,out] buf Buffer.
 */
void rom_msgbuf_consume_frame(rom_km_msgbuf_t *buf) {
    if (!buf->has_frame) return;

    buf->has_frame = 0;
    buf->count = 0;
    buf->tail = 0;
    buf->frame_len = 0;
    buf->partial_active = 0;
}

/*===========================================================================
 * Status Queries
 *===========================================================================*/

/**
 * @brief Return whether the buffer can accept a new frame (0 or 1).
 *
 * @param[in] buf Buffer to query.
 * @return 1 if a new frame can be accepted, 0 otherwise.
 */
uint8_t rom_msgbuf_can_accept_frame(const rom_km_msgbuf_t *buf) {
    return (uint8_t)(buf->has_frame ? 0u : 1u);
}

/**
 * @brief Return number of word slots available for writing.
 *
 * @param[in] buf Buffer.
 * @return Available space in words.
 */
uint16_t rom_msgbuf_space_available(const rom_km_msgbuf_t *buf) {
    return (uint16_t)(ROM_KM_MSGBUF_SIZE - buf->count);
}

/**
 * @brief Return whether a complete frame is present (0 or 1).
 *
 * @param[in] buf Buffer.
 * @return 1 if a frame is available, 0 otherwise.
 */
uint8_t rom_msgbuf_frame_available(const rom_km_msgbuf_t *buf) {
    return buf->has_frame ? 1u : 0u;
}

/**
 * @brief Return whether the current frame has been fully popped.
 *
 * @param[in] buf Buffer.
 * @return 1 if a frame is present and tail has reached frame_len, 0 otherwise.
 */
uint8_t rom_msgbuf_frame_empty(const rom_km_msgbuf_t *buf) {
    return (uint8_t)(buf->has_frame && buf->tail >= buf->frame_len);
}

/**
 * @brief Return whether the buffer is full.
 *
 * @param[in] buf Buffer.
 * @return 1 if full, 0 otherwise.
 */
uint8_t rom_msgbuf_is_full(const rom_km_msgbuf_t *buf) {
    return (buf->count >= ROM_KM_MSGBUF_SIZE) ? 1 : 0;
}

/**
 * @brief Return whether a partial frame write is in progress.
 *
 * @param[in] buf Buffer.
 * @return 1 if a partial frame is active, 0 otherwise.
 */
uint8_t rom_msgbuf_partial_active(const rom_km_msgbuf_t *buf) {
    return buf->partial_active ? 1u : 0u;
}

/**
 * @brief Flush the buffer (reset to empty).
 *
 * @param[in,out] buf Buffer.
 */
void rom_msgbuf_flush(rom_km_msgbuf_t *buf) {
    rom_msgbuf_init(buf);
}

/**
 * @brief Return whether buffer is full but has no complete frame (overflow).
 *
 * @param[in] buf Buffer.
 * @return 1 if full with only partial frame, 0 otherwise.
 */
uint8_t rom_msgbuf_has_only_partial(const rom_km_msgbuf_t *buf) {
    return (rom_msgbuf_is_full(buf) && !rom_msgbuf_frame_available(buf) &&
            rom_msgbuf_partial_active(buf))
               ? 1u
               : 0u;
}
