/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_msgbuf.c
 * @brief Mailbox <-> message-buffer interaction test
 *
 * Verifies that `rom_isr_mailbox()` correctly bridges the mailbox hardware FIFOs
 * and the firmware message buffers in both directions:
 * - `rom_tx_msgbuf` drains to the mailbox outbound FIFO as a framed message
 * - `rom_msg_tx_send()` re-arms outbound drain IRQ even when it starts disabled
 * - a partial TX ISR drain keeps the remaining frame queued and the drain IRQ armed
 * - masked `waitirq` wakes on pending mailbox IRQs before the ISR drains data
 * - inbound mailbox data drains into `rom_rx_msgbuf` as a complete frame
 * - when `rom_rx_msgbuf` already holds a frame, the ISR leaves inbound FIFO
 *   data pending and disables the inbound IRQ until software consumes it
 * - when the RX side holds only a partial frame plus residual FIFO data, the
 *   firmware must restore inbound IRQ delivery so the main loop cannot wedge
 *   permanently in waitirq
 *
 * The multi-word inbound subtest specifically guards against the bug where the
 * ISR misinterprets `rom_msgbuf_can_accept_frame()` as a word count and drains
 * only one word, preventing a payloaded frame from ever becoming available to
 * the main loop.
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_msgbuf
 */

#include "test_common.h"
#include "irq_common.h"
#include "rom_crc.h"
#include "rom_defs.h"
#include "rom_isr.h"
#include "rom_mailbox.h"
#include "rom_picorv32.h"
#include "rom_msg_rx.h"
#include "rom_msg_tx.h"
#include "rom_msgbuf.h"
#include "rom_state.h"
#include "km_mailbox_sep_regs.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

static uint32_t inbound_irq_enabled(void) {
    km_mailbox_km__irq_enable_reg_t irq_en = {.w = rom_mailbox_irq_enable_read()};
    return (uint32_t)irq_en.f.inbound_read_data_avail_en;
}

static uint32_t outbound_drain_irq_enabled(void) {
    km_mailbox_km__irq_enable_reg_t irq_en = {.w = rom_mailbox_irq_enable_read()};
    return (uint32_t)irq_en.f.outbound_write_space_avail_en;
}

static void reset_mailbox_state(void) {
    rom_mailbox_flush();
    rom_msgbuf_flush(&rom_rx_msgbuf);
    rom_msgbuf_flush(&rom_tx_msgbuf);
    rom_cmd_seq_num = 0;
    rom_resp_seq_num = 0;
    rom_mailbox_irq_enable_write(0u);
    test_delay(50);
}

static void send_sep_frame(const uint32_t *words, uint32_t len) {
    TEST_ASSERT(len > 0u, "frame length must be non-zero");

    for (uint32_t i = 0; i + 1u < len; i++) {
        if (!tb_sep_mbox_write(words[i], 5000u)) {
            TEST_FAIL("Failed to write SEP frame word %u", (unsigned)i);
        }
    }

    if (!tb_sep_mbox_write_separator_write(1u, 5000u)) {
        TEST_FAIL("Failed to set separator on final SEP frame word");
    }

    if (!tb_sep_mbox_write(words[len - 1u], 5000u)) {
        TEST_FAIL("Failed to write final SEP frame word");
    }
}

static void queue_tx_frame(const uint32_t *words, uint16_t len) {
    TEST_ASSERT(len > 0u, "tx frame length must be non-zero");

    for (uint16_t i = 0; i < len; i++) {
        uint8_t sep = (i == (uint16_t)(len - 1u)) ? 1u : 0u;
        int rc = rom_msgbuf_write_word(&rom_tx_msgbuf, words[i], sep);
        if (rc != 0) {
            TEST_FAIL("Failed to queue tx frame word %u", (unsigned)i);
        }
    }
}

static void fill_outbound_fifo(const uint32_t *words, uint16_t len) {
    TEST_ASSERT(len > 0u, "outbound fill length must be non-zero");

    for (uint16_t i = 0; i < len; i++) rom_mailbox_write_data(words[i]);
}

static void seed_rx_partial(uint32_t first_word, uint16_t len) {
    TEST_ASSERT(len > 0u, "partial seed length must be non-zero");

    for (uint16_t i = 0; i < len; i++) {
        int rc = rom_msgbuf_write_word(&rom_rx_msgbuf, first_word + (uint32_t)i, 0u);
        if (rc != 0) {
            TEST_FAIL("Failed to seed partial rx word %u", (unsigned)i);
        }
    }
}

static void expect_rx_frame(const uint32_t *expected_words, uint16_t expected_len) {
    uint16_t start = 0;
    uint16_t length = 0;

    TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 1u, "rx frame available");
    TEST_ASSERT_EQ(rom_msgbuf_peek_frame(&rom_rx_msgbuf, &start, &length), 0u,
                   "peek frame succeeds");
    TEST_ASSERT_EQ(start, 0u, "frame starts at index zero");
    TEST_ASSERT_EQ(length, expected_len, "frame length");
    TEST_ASSERT_EQ(rom_rx_msgbuf.count, expected_len, "buffer count");
    TEST_ASSERT_EQ(rom_rx_msgbuf.frame_len, expected_len, "stored frame length");
    TEST_ASSERT_EQ(rom_rx_msgbuf.tail, 0u, "tail before consume");

    for (uint16_t i = 0; i < expected_len; i++) {
        uint32_t word = 0;
        TEST_ASSERT_EQ(rom_msgbuf_pop_word(&rom_rx_msgbuf, &word), 0u,
                       "read buffered word succeeds");
        TEST_ASSERT_EQ(word, expected_words[i], "buffered word matches");
    }

    TEST_ASSERT_EQ(rom_rx_msgbuf.tail, expected_len, "tail after pop");
    rom_msgbuf_consume_frame(&rom_rx_msgbuf);
    TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 0u, "frame consumed");
    TEST_ASSERT_EQ(rom_rx_msgbuf.count, 0u, "buffer count reset");
}

static void expect_sep_frame(const uint32_t *expected_words, uint16_t expected_len) {
    for (uint16_t i = 0; i < expected_len; i++) {
        uint32_t word = 0;
        uint32_t status = 0;
        KM_MAILBOX_SEP_STATUS_REG_reg_u sep_status_u = {0};
        uint32_t expected_sep = (i == (uint16_t)(expected_len - 1u)) ? 1u : 0u;

        if (!tb_sep_mbox_read(&word, 5000u)) {
            TEST_FAIL("Failed to read SEP outbound word %u", (unsigned)i);
        }
        if (!tb_sep_mbox_status_read(&status, 5000u)) {
            TEST_FAIL("Failed to read SEP status after word %u", (unsigned)i);
        }

        sep_status_u.w = status;
        TEST_ASSERT_EQ(word, expected_words[i], "SEP outbound word");
        TEST_ASSERT_EQ((uint32_t)sep_status_u.f.outbound_separator, expected_sep,
                       "SEP outbound separator");
    }
}

static uint32_t make_response_header(uint8_t resp_id, uint8_t payload_len, uint8_t seq_num) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = seq_num;
    hdr.id = resp_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);
    return hdr.raw;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000u)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    TEST_SUBTEST_START("Single-word TX msgbuf drains to outbound mailbox");
    {
        static const uint32_t tx_frame[] = {0x1A2B3C4Du};

        reset_mailbox_state();
        queue_tx_frame(tx_frame, 1u);
        rom_mailbox_enable_outbound_drain_irq();

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 0u,
                       "single-word tx frame consumed by ISR");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 0u,
                       "outbound drain IRQ disabled when single-word tx empties");
        expect_sep_frame(tx_frame, 1u);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Multi-word TX msgbuf drains to outbound mailbox");
    {
        static const uint32_t tx_frame[] = {0xA1A2A3A4u, 0xB1B2B3B4u, 0xC1C2C3C4u};

        reset_mailbox_state();
        queue_tx_frame(tx_frame, 3u);
        rom_mailbox_enable_outbound_drain_irq();

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 0u,
                       "multi-word tx frame consumed by ISR");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 0u,
                       "outbound drain IRQ disabled when tx buffer empties");
        expect_sep_frame(tx_frame, 3u);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Disabled outbound drain IRQ is restored when TX data is queued");
    {
        const uint32_t expected_frame[] = {make_response_header(ROM_KM_RESP_KM_READY, 0u, 0u)};

        reset_mailbox_state();
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 0u, "outbound drain IRQ starts disabled");

        rom_msg_tx_send(ROM_KM_RESP_KM_READY, NULL, 0u);

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 1u,
                       "queued direct response frame is buffered");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 1u,
                       "queuing TX data re-enables outbound drain IRQ");

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 0u,
                       "queued response frame drains after ISR");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 0u,
                       "outbound drain IRQ disables after buffer drains");
        expect_sep_frame(expected_frame, 1u);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Partial TX ISR drain keeps remaining frame queued");
    {
        static const uint32_t prefill_words[] = {0x90000000u, 0x90000001u, 0x90000002u, 0x90000003u,
                                                 0x90000004u, 0x90000005u, 0x90000006u, 0x90000007u,
                                                 0x90000008u, 0x90000009u, 0x9000000Au, 0x9000000Bu,
                                                 0x9000000Cu, 0x9000000Du};
        static const uint32_t tx_frame[] = {0x12340001u, 0x12340002u, 0x12340003u};
        static const uint32_t remaining_fifo[] = {
            0x90000001u, 0x90000002u, 0x90000003u, 0x90000004u, 0x90000005u, 0x90000006u,
            0x90000007u, 0x90000008u, 0x90000009u, 0x9000000Au, 0x9000000Bu, 0x9000000Cu,
            0x9000000Du, 0x12340001u, 0x12340002u, 0x12340003u};
        uint16_t start = 0;
        uint16_t length = 0;
        uint32_t drained_word = 0;

        reset_mailbox_state();
        fill_outbound_fifo(prefill_words, 14u);
        queue_tx_frame(tx_frame, 3u);
        rom_mailbox_enable_outbound_drain_irq();

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 1u,
                       "remaining TX word stays buffered after partial ISR drain");
        TEST_ASSERT_EQ(rom_msgbuf_peek_frame(&rom_tx_msgbuf, &start, &length), 0u,
                       "peek remaining TX frame");
        TEST_ASSERT_EQ(length, 1u, "one TX word remains buffered");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 1u,
                       "outbound drain IRQ stays armed while TX frame remains");

        if (!tb_sep_mbox_read(&drained_word, 5000u)) {
            TEST_FAIL("Failed to drain one outbound word before retry");
        }
        TEST_ASSERT_EQ(drained_word, prefill_words[0], "prefill word drains first");

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_tx_msgbuf), 0u,
                       "remaining TX frame drains on second ISR");
        TEST_ASSERT_EQ(outbound_drain_irq_enabled(), 0u,
                       "outbound drain IRQ disables after final TX drain");
        expect_sep_frame(remaining_fifo, 16u);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Masked waitirq wakes on pending inbound mailbox IRQ");
    {
        static const uint32_t pending_frame[] = {0x0BADCAFEu};
        uint32_t old_mask = 0;

        reset_mailbox_state();
        rom_mailbox_enable_inbound_irq();
        old_mask = rom_picorv32_maskirq(0xFFFFFFFFu);
        send_sep_frame(pending_frame, 1u);
        test_delay(100u);

        rom_picorv32_waitirq();

        TEST_ASSERT(!rom_mailbox_inbound_empty(),
                    "masked waitirq returns before ISR drains inbound FIFO");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 0u,
                       "masked waitirq does not run mailbox ISR");

        rom_isr_mailbox();

        expect_rx_frame(pending_frame, 1u);
        TEST_ASSERT(rom_mailbox_inbound_empty(), "manual ISR drain clears pending mailbox frame");
        rom_picorv32_maskirq(old_mask);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Single-word frame drains into RX msgbuf");
    {
        static const uint32_t single_word_frame[] = {0xA5A5F00Du};

        reset_mailbox_state();
        rom_mailbox_enable_inbound_irq();
        send_sep_frame(single_word_frame, 1u);
        test_delay(100u);

        rom_isr_mailbox();

        expect_rx_frame(single_word_frame, 1u);
        TEST_ASSERT(rom_mailbox_inbound_empty(), "inbound FIFO empty after single-word drain");
        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u, "inbound IRQ remains enabled after full drain");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Multi-word frame drains into RX msgbuf");
    {
        static const uint32_t payload_frame[] = {0x11223344u, 0x55667788u, 0x99AABBCCu,
                                                 0xDDEEFF00u};

        reset_mailbox_state();
        rom_mailbox_enable_inbound_irq();
        send_sep_frame(payload_frame, 4u);
        test_delay(100u);

        rom_isr_mailbox();

        expect_rx_frame(payload_frame, 4u);
        TEST_ASSERT(rom_mailbox_inbound_empty(), "inbound FIFO empty after multi-word drain");
        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u,
                       "inbound IRQ remains enabled after multi-word drain");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Partial RX state with residual FIFO data must re-arm inbound IRQ");
    {
        /*
         * Model the Phase-2 race post-state directly: the unit harness cannot
         * interleave SEP writes while `rom_isr_mailbox()` is mid-drain, so seed
         * the resulting stuck condition instead.
         *
         * Expected recovery behavior: software must not leave
         * `inbound_read_data_avail_en` cleared when there is no complete RX
         * frame yet and unread inbound FIFO data remains, otherwise the main
         * loop can sleep forever in waitirq.
         */
        reset_mailbox_state();
        seed_rx_partial(0xABC00000u, 16u);

        if (!tb_sep_mbox_write(0xCAFEBABEu, 5000u)) {
            TEST_FAIL("Failed to queue residual inbound word");
        }
        test_delay(100u);

        rom_mailbox_disable_inbound_irq();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 0u,
                       "partial state has no complete frame");
        TEST_ASSERT_EQ(rom_msgbuf_has_only_partial(&rom_rx_msgbuf), 0u,
                       "partial state is not an overflow");
        TEST_ASSERT(!rom_mailbox_inbound_empty(), "residual inbound FIFO data is present");
        TEST_ASSERT_EQ(inbound_irq_enabled(), 0u,
                       "inbound IRQ starts disabled in stuck-state model");

        rom_msg_rx_process();

        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u,
                       "partial-only stuck state must re-enable inbound IRQ");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Existing RX frame blocks mailbox drain");
    {
        static const uint32_t existing_frame[] = {0x01020304u};
        static const uint32_t pending_frame[] = {0x11111111u, 0x22222222u};

        reset_mailbox_state();
        TEST_ASSERT_EQ(rom_msgbuf_write_word(&rom_rx_msgbuf, existing_frame[0], 1u), 0u,
                       "seed existing rx frame");

        rom_mailbox_enable_inbound_irq();
        send_sep_frame(pending_frame, 2u);
        test_delay(100u);

        rom_isr_mailbox();

        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 1u,
                       "existing frame still present");
        TEST_ASSERT(!rom_mailbox_inbound_empty(), "pending mailbox frame left in FIFO");
        TEST_ASSERT_EQ(inbound_irq_enabled(), 0u, "inbound IRQ disabled while frame is pending");

        expect_rx_frame(existing_frame, 1u);

        rom_mailbox_enable_inbound_irq();
        rom_isr_mailbox();

        expect_rx_frame(pending_frame, 2u);
        TEST_ASSERT(rom_mailbox_inbound_empty(),
                    "pending frame drains after rx buffer is consumed");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
