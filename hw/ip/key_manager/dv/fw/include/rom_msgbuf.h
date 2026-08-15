/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msgbuf.h
 * @brief Linear message buffer with single-frame tracking for Key Manager firmware
 *
 * Word-granularity linear buffer that holds at most one complete message
 * frame at a time.  Each new frame starts at index 0.  The ISR writes
 * incoming mailbox words via rom_msgbuf_write_word(); the main loop
 * consumes the single frame via rom_msgbuf_peek_frame / rom_msgbuf_pop_word /
 * rom_msgbuf_consume_frame.
 *
 * IRQ safety: main-loop code that mutates a buffer shared with the mailbox
 * ISR must mask the mailbox IRQ (ROM_KM_IRQ_MBOX_BIT) for the duration of
 * the mutation. The ISR is the sole writer to rx_buf and sole
 * reader of tx_buf; the main loop is the sole writer to tx_buf and sole
 * reader of rx_buf.
 */

#ifndef ROM_MSGBUF_H
#define ROM_MSGBUF_H

#include <stdint.h>
#include "rom_defs.h"

/*===========================================================================
 * Types
 *===========================================================================*/

/** @brief Linear message buffer with single-frame bookkeeping. */
typedef struct {
    uint32_t data[ROM_KM_MSGBUF_SIZE]; /**< Word storage (each frame starts at 0) */
    uint16_t count;                    /**< Words in buffer (write index when building) */
    uint8_t has_frame;                 /**< 1 if one complete frame is present */
    uint16_t frame_len;                /**< Length in words of the frame */
    uint16_t tail;                     /**< Next read index (0 .. frame_len) */
    uint8_t partial_active;            /**< 1 if a frame write is in progress */
} rom_km_msgbuf_t;

/*===========================================================================
 * Initialization
 *===========================================================================*/

/**
 * @brief Initialize (or reinitialize) a message buffer.
 *
 * Zeros all fields, leaving the buffer empty with no partial frame.
 *
 * @param buf Buffer to initialize.
 */
void rom_msgbuf_init(rom_km_msgbuf_t *buf);

/*===========================================================================
 * Write Path (ISR side)
 *===========================================================================*/

/**
 * @brief Write one 32-bit word into the buffer.
 *
 * Stores @p word at the next slot (each new frame starts at index 0).
 * If @p separator is 1, the current partial frame is closed and becomes
 * the single complete frame.  If a frame is already present (has_frame),
 * further writes return -1 until the frame is consumed.
 *
 * @param buf Target buffer.
 * @param word Data word to enqueue.
 * @param separator 1 to close the current frame, 0 to continue.
 * @return 0 on success, -1 if buffer full or frame already present.
 */
int rom_msgbuf_write_word(rom_km_msgbuf_t *buf, uint32_t word, uint8_t separator);

/*===========================================================================
 * Read Path (main-loop side)
 *===========================================================================*/

/**
 * @brief Peek at the next word from the current frame.
 *
 * Returns the word at tail without advancing the tail. The frame remains
 * present and must still be popped/consumed explicitly.
 *
 * @param buf Source buffer.
 * @param word Receives the peeked word.
 * @return 0 on success, -1 if the buffer is empty.
 */
int rom_msgbuf_peek_word(const rom_km_msgbuf_t *buf, uint32_t *word);

/**
 * @brief Pop one word from the current frame.
 *
 * Returns the word at tail and advances the tail. Popping the last word does
 * not discard the frame bookkeeping; callers must explicitly call
 * rom_msgbuf_consume_frame() once the frame is fully processed.
 *
 * @param buf Source buffer.
 * @param word Receives the popped word.
 * @return 0 on success, -1 if the buffer is empty or already exhausted.
 */
int rom_msgbuf_pop_word(rom_km_msgbuf_t *buf, uint32_t *word);

/**
 * @brief Return whether a complete frame is available (0 or 1).
 *
 * @param buf Buffer to query.
 * @return 1 if a frame is available, 0 otherwise.
 */
uint8_t rom_msgbuf_frame_available(const rom_km_msgbuf_t *buf);

/**
 * @brief Peek at the current frame without consuming it.
 *
 * @param buf Buffer to query.
 * @param start Receives the next read index in data[] (0 or tail).
 * @param length Receives the remaining word count (frame_len - tail).
 * @return 0 if a frame is available, -1 if no frame.
 */
int rom_msgbuf_peek_frame(const rom_km_msgbuf_t *buf, uint16_t *start, uint16_t *length);

/**
 * @brief Discard the current frame.
 *
 * Clears has_frame and resets state so the next frame starts at index 0.
 *
 * @param buf Buffer to modify.
 */
void rom_msgbuf_consume_frame(rom_km_msgbuf_t *buf);

/*===========================================================================
 * Status Queries
 *===========================================================================*/

/**
 * @brief Return the number of free word slots.
 *
 * @param buf Buffer to query.
 * @return ROM_KM_MSGBUF_SIZE minus the current word count.
 */
uint16_t rom_msgbuf_space_available(const rom_km_msgbuf_t *buf);

/**
 * @brief Return whether the current frame has been fully popped.
 *
 * This is true only when a frame is still present (`has_frame == 1`) but the
 * read tail has advanced to the end of that frame, so the caller must still
 * explicitly consume it with rom_msgbuf_consume_frame().
 *
 * @param buf Buffer to query.
 * @return 1 if the current frame is empty and awaiting explicit consume, 0 otherwise.
 */
uint8_t rom_msgbuf_frame_empty(const rom_km_msgbuf_t *buf);

/**
 * @brief Return whether the buffer can accept a new frame (0 or 1).
 *
 * With single-frame support, returns 1 only when no complete frame is
 * present.
 *
 * @param buf Buffer to query.
 * @return 1 if a new frame can be accepted, 0 otherwise.
 */
uint8_t rom_msgbuf_can_accept_frame(const rom_km_msgbuf_t *buf);

/**
 * @brief Check whether the buffer is completely full.
 *
 * @param buf Buffer to query.
 * @return 1 if full, 0 otherwise.
 */
uint8_t rom_msgbuf_is_full(const rom_km_msgbuf_t *buf);

/**
 * @brief Return whether a partial frame write is currently in progress.
 *
 * This is set after one or more non-separator writes have been accepted and is
 * cleared when the frame is either terminated or the buffer is reset.
 *
 * @param buf Buffer to query.
 * @return 1 if a partial frame is active, 0 otherwise.
 */
uint8_t rom_msgbuf_partial_active(const rom_km_msgbuf_t *buf);

/**
 * @brief Flush the buffer to its empty/initialized state.
 *
 * @param buf Buffer to flush.
 */
void rom_msgbuf_flush(rom_km_msgbuf_t *buf);

/**
 * @brief Check for "full with only a partial frame" (unterminated message).
 *
 * Returns 1 when the buffer is full, has no complete frame, and a
 * partial frame is active.
 *
 * @param buf Buffer to query.
 * @return 1 if the condition holds, 0 otherwise.
 */
uint8_t rom_msgbuf_has_only_partial(const rom_km_msgbuf_t *buf);

#endif /* ROM_MSGBUF_H */
