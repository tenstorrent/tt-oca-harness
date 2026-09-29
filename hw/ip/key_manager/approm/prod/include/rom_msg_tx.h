/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msg_tx.h
 * @brief Outgoing message handler for Key Manager firmware
 *
 * Constructs complete response frames (header + payload + CRC) and
 * writes them to either the software TX message buffer or directly
 * to the outgoing mailbox FIFO.
 */

#ifndef ROM_MSG_TX_H
#define ROM_MSG_TX_H

#include <stdint.h>

/**
 * @brief Send a response frame via the software TX buffer.
 *
 * Builds a frame (header, optional payload, optional CRC-32C),
 * auto-increments the global response sequence number, and writes
 * the frame into rom_tx_msgbuf.  The ISR drains the TX buffer
 * into the outbound mailbox FIFO asynchronously.
 *
 * If the TX buffer is full, enables the outbound write_space_avail
 * IRQ and spins until the ISR frees space.
 *
 * @param resp_id Response ID (ROM_KM_RESP_CMD, ROM_KM_RESP_KM_READY, etc.)
 * @param payload Pointer to payload words (NULL if payload_len == 0).
 * @param payload_len Number of 32-bit payload words (0..255).
 */
void rom_msg_tx_send(uint8_t resp_id, const uint32_t *payload, uint8_t payload_len);

/**
 * @brief Send a response frame directly to the outbound mailbox FIFO.
 *
 * Same frame format as rom_msg_tx_send() but bypasses the software
 * TX buffer entirely, writing words straight to the mailbox
 * WRITE_DATA register.  Used for fault messages sent from ISR
 * context (RESP_RECOVERABLE_FAULT, RESP_UNRECOVERABLE_FAULT).
 *
 * @param resp_id Response ID.
 * @param payload Pointer to payload words (NULL if payload_len == 0).
 * @param payload_len Number of 32-bit payload words (0..255).
 */
void rom_msg_tx_send_direct(uint8_t resp_id, const uint32_t *payload, uint8_t payload_len)
    __attribute__((cold));

#endif /* ROM_MSG_TX_H */
