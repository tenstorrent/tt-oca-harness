/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_msg_rx.c
 * @brief Inbound command frame processing.
 *
 * Consumes at most one buffered frame per call, validates protocol fields
 * in priority order, dispatches the command, and sends a `RESP_CMD`.
 */

#include "rom_defs.h"
#include "rom_state.h"
#include "rom_msg_rx.h"
#include "rom_msg_tx.h"
#include "rom_cmd.h"
#include "rom_crc.h"
#include "rom_msgbuf.h"
#include "rom_isr.h"
#include "rom_mailbox.h"
#include "rom_kmcsr.h"
#include "rom_picorv32.h"
#include "rom_secutil.h"

/*===========================================================================
 * IRQ-Masked Buffer Helpers
 *===========================================================================*/

/**
 * @brief Reads one RX word while masking mailbox IRQ.
 *
 * @param word Output word.
 */
static void rx_pop_word(uint32_t *word) {
    uint32_t saved = rom_picorv32_maskirq(0xFFFFFFFF);
    rom_picorv32_maskirq(saved | ROM_KM_IRQ_MBOX_BIT);
    rom_msgbuf_pop_word(&rom_rx_msgbuf, word);
    rom_picorv32_maskirq(saved);
}

/**
 * @brief Consumes current RX frame while mailbox IRQ is masked.
 *
 * Re-enables inbound mailbox IRQ after the frame is dropped.
 */
static void rx_consume_frame(void) {
    uint32_t saved = rom_picorv32_maskirq(0xFFFFFFFF);
    rom_picorv32_maskirq(saved | ROM_KM_IRQ_MBOX_BIT);
    rom_msgbuf_consume_frame(&rom_rx_msgbuf);
    rom_picorv32_maskirq(saved);
    rom_mailbox_enable_inbound_irq();
}

/*===========================================================================
 * Response Helper
 *===========================================================================*/

/**
 * @brief Build and send a RESP_CMD frame.
 *
 * @param cmd_seq Command sequence number echo.
 * @param cmd_id Command ID echo.
 * @param rc Signed return code.
 * @param has_arg Non-zero when `arg` is valid.
 * @param arg Optional return argument.
 */
static void send_resp_cmd(uint8_t cmd_seq, uint8_t cmd_id, int8_t rc, uint8_t has_arg,
                          uint32_t arg) {
    uint32_t payload[4];
    uint8_t len;

    payload[0] = (uint32_t)cmd_seq;
    payload[1] = (uint32_t)cmd_id;
    payload[2] = (uint32_t)(uint8_t)rc;

    if (has_arg) {
        payload[3] = arg;
        len = 4;
    } else {
        len = 3;
    }

    rom_msg_tx_send(ROM_KM_RESP_CMD, payload, len);
}

/*===========================================================================
 * Public API
 *===========================================================================*/

/**
 * @brief Processes one complete inbound frame.
 *
 * No-ops when no complete frame is available.
 */
void rom_msg_rx_process(void) {
    /*
     * Step 1: Check degenerate overflow — buffer full with only a partial
     * frame means one unterminated message consumed all space.
     */
    if (rom_msgbuf_has_only_partial(&rom_rx_msgbuf)) {
        rom_mailbox_flush();
        rom_msgbuf_flush(&rom_rx_msgbuf);
        rom_msgbuf_flush(&rom_tx_msgbuf);
        rom_cmd_seq_num = 0;
        rom_resp_seq_num = 0;
        rom_trigger_recoverable(ROM_KM_RFAULT_RX_BUFF_OFLOW);
        rom_mailbox_enable_inbound_irq();
        return;
    }

    /*
     * Step 2: Bail if no complete frames are available.
     *
     * If mailbox data remains pending and the RX buffer still has space, make
     * sure the inbound IRQ is armed before sleeping again. This covers the
     * case where the ISR drained a partial frame, SEP refilled the FIFO during
     * that drain, and the IRQ was left disabled even though firmware can still
     * accept more words.
     */
    if (rom_msgbuf_frame_available(&rom_rx_msgbuf) == 0) {
        if (!rom_mailbox_inbound_empty() && rom_msgbuf_space_available(&rom_rx_msgbuf) > 0u)
            rom_mailbox_enable_inbound_irq();
        return;
    }

    /* Step 3: Peek at the oldest frame for its length. */
    uint16_t frame_start, frame_len;
    rom_msgbuf_peek_frame(&rom_rx_msgbuf, &frame_start, &frame_len);

    /* Step 4: Read header word. */
    uint32_t hdr_word;
    rx_pop_word(&hdr_word);

    rom_km_msg_header_t header;
    header.raw = hdr_word;

    /* Step 5: Validate header CRC-8/ROHC over bytes [0..2]. */
    uint8_t computed_hdr_crc = rom_crc8_rohc((const uint8_t *)&hdr_word, 3);
    if (computed_hdr_crc != header.header_crc8) {
        rx_consume_frame();
        send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_HEADER_CRC, 1,
                      (uint32_t)computed_hdr_crc);
        return;
    }

    /* Step 6: Validate sequence number. */
    if (header.seq_num != rom_cmd_seq_num) {
        rx_consume_frame();
        send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_CMD_NOSEQ, 1, (uint32_t)rom_cmd_seq_num);
        return;
    }
    rom_cmd_seq_num++;

    /* Step 7: Validate command ID. */
    if (!ROM_KM_CMD_IS_VALID(header.id)) {
        rx_consume_frame();
        send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_INVALID_CMD, 0, 0);
        return;
    }

    /*
     * Step 8: Validate payload length.
     * Expected frame length = 1 (header) + payload_len + (payload_len > 0 ? 1 : 0) (CRC).
     */
    uint16_t expected_frame_len =
        (uint16_t)(1u + (unsigned)header.payload_len + (header.payload_len > 0 ? 1u : 0u));
    if (frame_len != expected_frame_len) {
        uint32_t actual_payload =
            (frame_len > 1) ? (uint32_t)(frame_len - 1 - (frame_len > 2 ? 1 : 0)) : 0u;
        rx_consume_frame();
        send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_INVALID_LEN, 1, actual_payload);
        return;
    }

    /* Step 9: Read payload words (if any). */
    static uint32_t payload[ROM_KM_MAX_PAYLOAD_LEN];
    for (uint8_t i = 0; i < header.payload_len; i++) rx_pop_word(&payload[i]);

    /* Step 10: Validate payload CRC-32C (if payload present). */
    if (header.payload_len > 0) {
        uint32_t rx_crc;
        rx_pop_word(&rx_crc);

        uint32_t computed_crc =
            rom_crc32c((const uint8_t *)payload, (uint32_t)header.payload_len * 4);
        if (rx_crc != computed_crc) {
            /* CMD_KEY_LOAD carries a plaintext key in the shared payload[]
             * buffer; clear the populated words before bailing out. */
            if (header.id == ROM_KM_CMD_KEY_LOAD)
                rom_secure_memzero(payload, (size_t)header.payload_len * sizeof(payload[0]));
            rx_consume_frame();
            send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_PAYLOAD_CRC, 1, computed_crc);
            return;
        }
    }

    /*
     * Step 11: RECOVERABLE_ERR filter — only a subset of query/ack
     * commands are permitted while the error flag is asserted.
     */
    if (rom_kmcsr_recoverable_err_bit_read()) {
        if (header.id != ROM_KM_CMD_HW_VER && header.id != ROM_KM_CMD_ROM_VER &&
            header.id != ROM_KM_CMD_SRAM_VER && header.id != ROM_KM_CMD_STAT &&
            header.id != ROM_KM_CMD_RECOV_ACK) {
            if (header.id == ROM_KM_CMD_KEY_LOAD)
                rom_secure_memzero(payload, (size_t)header.payload_len * sizeof(payload[0]));
            rx_consume_frame();
            send_resp_cmd(header.seq_num, header.id, ROM_KM_RC_FAILURE, 0, 0);
            return;
        }
    }

    /* Step 12: Dispatch to command handler. */
    rom_km_cmd_result_t result =
        rom_cmd_dispatch(header.id, header.seq_num, header.payload_len, payload);

    /* Wipe the plaintext key from the shared payload[] buffer once the
     * CMD_KEY_LOAD handler has consumed it. */
    if (header.id == ROM_KM_CMD_KEY_LOAD)
        rom_secure_memzero(payload, (size_t)header.payload_len * sizeof(payload[0]));

    /* Step 13: Drop the fully processed frame, then send RESP_CMD. */
    rx_consume_frame();
    send_resp_cmd(header.seq_num, header.id, result.return_code, result.has_arg, result.return_arg);
}
