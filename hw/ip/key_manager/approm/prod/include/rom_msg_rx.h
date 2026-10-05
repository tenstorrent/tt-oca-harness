/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msg_rx.h
 * @brief Inbound message processing for Key Manager firmware
 *
 * Processes one complete command frame per call: validates header CRC,
 * sequence number, command ID, payload length, payload CRC, then
 * dispatches to the appropriate command handler and sends RESP_CMD.
 */

#ifndef ROM_MSG_RX_H
#define ROM_MSG_RX_H

/**
 * @brief Process one complete inbound command frame.
 *
 * Called from the main event loop when rom_msgbuf_frame_available()
 * indicates at least one complete frame in rom_rx_msgbuf.
 *
 * Validation order (each step returns an error response on failure):
 *   1. Buffer overflow (partial-only) check
 *   2. Header CRC-8/ROHC
 *   3. Sequence number
 *   4. Command ID range
 *   5. Payload length vs. frame size
 *   6. Payload CRC-32C (if payload present)
 *   7. RECOVERABLE_ERR command filter
 *   8. Command dispatch
 */
void rom_msg_rx_process(void);

#endif /* ROM_MSG_RX_H */
