/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_main_step.c
 * @brief Direct coverage for one real `rom_main_step()` iteration.
 *
 * Verifies that `rom_main_step()` uses the masked waitirq path safely and still
 * performs RX-side housekeeping before sleeping.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_main_step
 */

#include "test_common.h"
#include "rom_main_step.h"
#include "rom_isr.h"
#include "rom_mailbox.h"
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

static void reset_mailbox_state(void) {
    rom_mailbox_flush();
    rom_msgbuf_flush(&rom_rx_msgbuf);
    rom_msgbuf_flush(&rom_tx_msgbuf);
    rom_cmd_seq_num = 0;
    rom_resp_seq_num = 0;
    rom_mailbox_irq_enable_write(0u);
    test_delay(50u);
}

static void send_sep_frame(const uint32_t *words, uint32_t len) {
    TEST_ASSERT(len > 0u, "frame length must be non-zero");

    for (uint32_t i = 0; i + 1u < len; i++) {
        if (!tb_sep_mbox_write(words[i], 5000u))
            TEST_FAIL("Failed to write SEP frame word %u", (unsigned)i);
    }

    if (!tb_sep_mbox_write_separator_write(1u, 5000u))
        TEST_FAIL("Failed to set separator on final SEP frame word");

    if (!tb_sep_mbox_write(words[len - 1u], 5000u))
        TEST_FAIL("Failed to write final SEP frame word");
}

static void seed_rx_partial(uint32_t first_word, uint16_t len) {
    TEST_ASSERT(len > 0u, "partial seed length must be non-zero");

    for (uint16_t i = 0; i < len; i++) {
        int rc = rom_msgbuf_write_word(&rom_rx_msgbuf, first_word + (uint32_t)i, 0u);
        if (rc != 0) TEST_FAIL("Failed to seed partial rx word %u", (unsigned)i);
    }
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(200000u)) TEST_FAIL("Failed to set testbench timeout");

    TEST_SUBTEST_START("rom_main_step wakes on pending mailbox IRQ without draining FIFO");
    {
        static const uint32_t pending_frame[] = {0x0BADCAFEu};

        reset_mailbox_state();
        rom_mailbox_enable_inbound_irq();
        send_sep_frame(pending_frame, 1u);
        test_delay(100u);

        rom_main_step();

        TEST_ASSERT(!rom_mailbox_inbound_empty(),
                    "rom_main_step returns with mailbox data still pending");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 0u,
                       "rom_main_step does not drain mailbox data itself");
        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u, "inbound IRQ remains enabled after wake");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("rom_main_step runs RX housekeeping before sleeping");
    {
        static const uint32_t pending_word[] = {0x1234FEDCu};

        reset_mailbox_state();
        seed_rx_partial(0xABC00000u, 16u);
        if (!tb_sep_mbox_write(pending_word[0], 5000u))
            TEST_FAIL("Failed to queue residual inbound word");
        test_delay(100u);
        rom_mailbox_disable_inbound_irq();

        rom_main_step();

        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u,
                       "rom_main_step re-arms inbound IRQ via rom_msg_rx_process");
        TEST_ASSERT(!rom_mailbox_inbound_empty(), "residual FIFO data remains pending after wake");
        TEST_ASSERT_EQ(rom_msgbuf_frame_available(&rom_rx_msgbuf), 0u,
                       "partial RX state still has no complete frame");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
