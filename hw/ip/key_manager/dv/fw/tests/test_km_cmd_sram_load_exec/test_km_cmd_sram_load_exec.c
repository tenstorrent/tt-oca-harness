/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_sram_load_exec.c
 * @brief CMD_SRAM_LOAD_EXEC end-to-end: load a mutable-firmware blob and execute it.
 *
 * Acts as the SEP: sends CMD_SRAM_LOAD_EXEC with FW_WORDS=14, then streams
 * a 14-word minimal mutable-firmware blob + valid CRC-32 into the inbound FIFO.
 *
 * The KM handler:
 *   1. Validates the command and fw_words count.
 *   2. Sends RESP_CMD success directly (before polling the FIFO for the image).
 *   3. Streams 14 image words + CRC from the inbound FIFO into SRAM 0x4000.
 *   4. Verifies the CRC-32 (must match).
 *   5. Sets sram_fw_size, locks sensitive data, writes the SRAM firmware-region
 *      lock mask, scrambles unlocked SRAM, clears GPRs, and jumps to 0x4000.
 *
 * The mutable firmware blob (mutable_fw_blob_small, 14 words) executes at 0x4000
 * and writes TEST_RESULT=1 and TEST_SIGNATURE=TEST_PASS_SIGNATURE to the KMCSR
 * test registers, signalling success to the cocotb testbench.
 *
 * The call to rom_msg_rx_process() below never returns; test "pass" is reported
 * by the mutable blob writing TEST_PASS_SIGNATURE.
 *
 * Mailbox FIFO depth = 16 words.  Image frame (14 + 1 CRC = 15 words) is
 * written AFTER the ISR has drained the 3-word command frame, so the FIFO
 * never exceeds 15 words simultaneously.  CPU IRQs are masked before writing
 * image words to prevent the ISR from consuming them.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_sram_load_exec
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_picorv32.h"
#include "test_mutable_fw_blob.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(2000000)) TEST_FAIL("timeout set failed");

    if (!tb_drbg_set_seed(0xE011u, 5000)) TEST_FAIL("drbg set seed failed");

    rom_boot_init();

    /* Drain RESP_KM_READY (single header word). */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    /*=========================================================================
     * Build the CMD_SRAM_LOAD_EXEC command frame.
     * Frame layout: [header][fw_words_payload][sep|payload_crc]  (3 words)
     *=========================================================================*/
    uint8_t seq = 0;
    uint32_t fw_words = MUTABLE_FW_BLOB_SMALL_WORDS; /* 14 */

    rom_km_msg_header_t hdr;
    hdr.seq_num = seq;
    hdr.id = ROM_KM_CMD_SRAM_LOAD_EXEC;
    hdr.payload_len = 1;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    uint32_t payload_crc = rom_crc32c((const uint8_t *)&fw_words, 4u);

    /*
     * Mask all CPU IRQs now so that:
     *   (a) The ISR cannot fire automatically after we call rom_isr_mailbox()
     *       below and interfere with the image words we subsequently load.
     *   (b) The handler can safely re-mask them as part of the handover.
     * The TB command interface (KMCSR register polling) is not affected by
     * the maskirq state; tb_sep_mbox_write calls still work.
     */
    (void)rom_picorv32_maskirq(0xFFFFFFFFu);

    /*
     * Step 1: Write the command frame (3 words) to the inbound FIFO.
     */
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    if (!tb_sep_mbox_write(fw_words, 5000)) TEST_FAIL("fw_words write failed");
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(payload_crc, 5000)) TEST_FAIL("payload CRC write failed");

    /*
     * Step 2: Explicitly drain the command frame from the FIFO into
     * rom_rx_msgbuf.  The ISR reads 3 words, detects the separator bit on
     * the CRC word, marks the frame complete, and leaves the FIFO empty.
     * Because the FIFO is empty after this call, the ISR does NOT disable the
     * inbound FIFO IRQ (that would only happen if image words were already
     * present); CPU IRQ masking (step 0) prevents any auto-ISR from firing
     * when we load image words in step 3.
     */
    test_delay(100);
    rom_isr_mailbox();

    /*
     * Step 3: Write the image frame (14 image words + sep|CRC = 15 words).
     * 15 words fits within the 16-word FIFO.  CPU IRQs are masked, so the
     * ISR cannot fire and consume image words.
     */
    for (uint32_t i = 0; i < MUTABLE_FW_BLOB_SMALL_WORDS; i++) {
        if (!tb_sep_mbox_write(mutable_fw_blob_small[i], 5000))
            TEST_FAIL("image word %u write failed", (unsigned)i);
    }
    uint32_t image_crc =
        rom_crc32c((const uint8_t *)mutable_fw_blob_small, MUTABLE_FW_BLOB_SMALL_WORDS * 4u);
    if (!tb_sep_mbox_write_separator_write(1, 5000))
        TEST_FAIL("image frame separator write failed");
    if (!tb_sep_mbox_write(image_crc, 5000)) TEST_FAIL("image CRC write failed");

    /*
     * Step 4: Dispatch the command.
     *
     * rom_msg_rx_process() dispatches to rom_cmd_sram_load_exec, which calls
     * rom_handover_load_and_exec.  That function:
     *   - Validates fw_words against the live stack (should pass for 14 words).
     *   - Sends RESP_CMD success directly to the outbound FIFO.
     *   - Streams 14 image words + CRC from the inbound FIFO (already loaded).
     *   - Verifies CRC-32 (matches → success).
     *   - Sets sram_fw_size = 56 in rom_persist.
     *   - Calls rom_handover_finish: lock OTP, lock rom_persist, set SRAM
     *     write-lock for region 0 (covers 0x4000..0x41FF), disable all IRQs,
     *     call rom_handover_jump.S.
     *   - rom_handover_jump.S: scrambles unlocked SRAM, clears GPRs, jumps
     *     to 0x4000.
     *
     * The mutable blob at 0x4000 executes and writes:
     *   TEST_RESULT    = 1                  (0xE110)
     *   TEST_SIGNATURE = TEST_PASS_SIGNATURE (0xE114)
     *
     * This call never returns.
     */

    /* Arm the TB's autonomous outbound drainer so the SEP-side reads the
     * RESP_CMD the handover sends.  rom_handover_finish() spins until the
     * outbound FIFO is empty before flushing it, and this CPU cannot drain it
     * itself once inside the handover. */
    if (!tb_sep_mbox_drain_enable(1, 5000)) TEST_FAIL("failed to arm outbound drainer");

    rom_msg_rx_process();

    /* Should never reach here */
    TEST_FAIL("CMD_SRAM_LOAD_EXEC should have jumped to mutable firmware at 0x4000");
    return 0;
}
