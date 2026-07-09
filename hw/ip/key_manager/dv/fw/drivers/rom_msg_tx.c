/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msg_tx.c
 * @brief Outgoing response frame construction and transmit.
 *
 * Builds protocol-compliant response frames and sends them either through
 * the software TX buffer or directly to mailbox hardware.
 */

#include "rom_msg_tx.h"
#include "rom_defs.h"
#include "rom_crc.h"
#include "rom_msgbuf.h"
#include "rom_state.h"
#include "rom_mailbox.h"
#include "rom_isr.h"
#include "rom_picorv32.h"

/*===========================================================================
 * Internal Helpers
 *===========================================================================*/

/**
 * @brief Builds response header with incremented sequence number.
 *
 * @param resp_id Response identifier.
 * @param payload_len Payload length in words.
 * @return Header structure with seq_num, id, payload_len, header_crc8.
 */
static rom_km_msg_header_t build_header(uint8_t resp_id, uint8_t payload_len) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = rom_resp_seq_num++;
    hdr.id = resp_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);
    return hdr;
}

/**
 * @brief Wait until the outbound mailbox FIFO has room for one word.
 */
static void tx_wait_outbound_space(void) {
    while (rom_mailbox_outbound_space_available_read() == 0u) {
    }
}

/**
 * @brief Writes one word to TX buffer, retrying while full.
 *
 * @param word Word to enqueue.
 * @param separator Non-zero when this word closes the frame.
 */
static void tx_buf_write(uint32_t word, uint8_t separator) {
    for (;;) {
        while (rom_msgbuf_is_full(&rom_tx_msgbuf)) rom_mailbox_enable_outbound_drain_irq();

        uint32_t saved = rom_picorv32_maskirq(0xFFFFFFFF);
        rom_picorv32_maskirq(saved | ROM_KM_IRQ_MBOX_BIT);
        int r = rom_msgbuf_write_word(&rom_tx_msgbuf, word, separator);
        rom_picorv32_maskirq(saved);

        if (r == 0) break;

        /* Buffer full or frame already present; allow ISR to drain then retry. */
        rom_mailbox_enable_outbound_drain_irq();
    }
}

/*===========================================================================
 * Public API
 *===========================================================================*/

/**
 * @brief Enqueues a response frame into TX software buffer.
 *
 * @param resp_id Response identifier.
 * @param payload Payload words, or `NULL` for empty payload.
 * @param payload_len Payload length in words.
 */
void rom_msg_tx_send(uint8_t resp_id, const uint32_t *payload, uint8_t payload_len) {
    rom_km_msg_header_t hdr = build_header(resp_id, payload_len);

    if (payload_len == 0) {
        tx_buf_write(hdr.raw, 1);
    } else {
        tx_buf_write(hdr.raw, 0);
        for (uint8_t i = 0; i < payload_len; i++) tx_buf_write(payload[i], 0);
        uint32_t crc = rom_crc32c((const uint8_t *)payload, (uint32_t)payload_len * 4);
        tx_buf_write(crc, 1);
    }

    /* Ensure ISR will drain the TX buffer (even when buffer was not full). */
    rom_mailbox_enable_outbound_drain_irq();
}

/**
 * @brief Writes a response frame directly to mailbox FIFO.
 *
 * Used by fault/boot paths where buffered TX is not appropriate.
 *
 * @param resp_id Response identifier.
 * @param payload Payload words, or `NULL` for empty payload.
 * @param payload_len Payload length in words.
 */
__attribute__((cold)) void rom_msg_tx_send_direct(uint8_t resp_id, const uint32_t *payload,
                                                  uint8_t payload_len) {
    rom_km_msg_header_t hdr = build_header(resp_id, payload_len);

    if (payload_len == 0) {
        rom_mailbox_set_write_separator();
        tx_wait_outbound_space();
        rom_mailbox_write_data(hdr.raw);
        return;
    }

    tx_wait_outbound_space();
    rom_mailbox_write_data(hdr.raw);

    for (uint8_t i = 0; i < payload_len; i++) {
        tx_wait_outbound_space();
        rom_mailbox_write_data(payload[i]);
    }

    uint32_t crc = rom_crc32c((const uint8_t *)payload, (uint32_t)payload_len * 4);
    rom_mailbox_set_write_separator();
    tx_wait_outbound_space();
    rom_mailbox_write_data(crc);
}
