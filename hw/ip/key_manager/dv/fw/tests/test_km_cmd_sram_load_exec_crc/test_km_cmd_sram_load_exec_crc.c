/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_sram_load_exec_crc.c
 * @brief CMD_SRAM_LOAD_EXEC bad-CRC → ROM_KM_UFAULT_FW_CRC unrecoverable fault.
 *
 * Sends CMD_SRAM_LOAD_EXEC with a valid 14-word image but a deliberately
 * corrupted CRC-32 trailer.  The handler streams the image, computes the
 * expected CRC, detects the mismatch, and triggers an unrecoverable fault
 * (ROM_KM_UFAULT_FW_CRC).
 *
 * Pattern follows test_km_unrec_hw_rom_parity.c:
 *   - First run  : arm unrecoverable watch, send bad-CRC image, fault triggers.
 *   - Second run : verify restart was due to unrecoverable fault and the
 *                  captured fault code equals ROM_KM_UFAULT_FW_CRC.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_sram_load_exec_crc
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

    /*
     * Second run: after the unrecoverable fault the testbench resets the DUT.
     * Check this before any initialization so we return quickly.
     */
    if (tb_check_unrecoverable_restart(1000)) {
        uint32_t fault_code;
        if (!tb_get_unrecoverable_fault_code(1000, &fault_code)) {
            TEST_FAIL("tb_get_unrecoverable_fault_code failed");
        }
        uint32_t expected = (uint32_t)(int32_t)ROM_KM_UFAULT_FW_CRC;
        if (fault_code != expected) {
            TEST_FAIL("wrong fault code: expected ROM_KM_UFAULT_FW_CRC (0x%08X), "
                      "got 0x%08X",
                      expected, fault_code);
        }
        TEST_PASS();
        return 0;
    }

    /*
     * First run: trigger the fault.
     */
    if (!tb_set_timeout(2000000)) TEST_FAIL("timeout set failed");

    if (!tb_drbg_set_seed(0xE020u, 5000)) TEST_FAIL("drbg set seed failed");

    if (!tb_set_unrecoverable_watch(1, 1000u)) TEST_FAIL("tb_set_unrecoverable_watch failed");

    rom_boot_init();

    /* Drain RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    /*
     * Build and send the CMD_SRAM_LOAD_EXEC command frame.
     * Frame: [header][fw_words_payload][sep|payload_crc]   (3 words)
     */
    uint8_t seq = 0;
    uint32_t fw_words = MUTABLE_FW_BLOB_SMALL_WORDS; /* 14 */

    rom_km_msg_header_t hdr;
    hdr.seq_num = seq;
    hdr.id = ROM_KM_CMD_SRAM_LOAD_EXEC;
    hdr.payload_len = 1;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    uint32_t payload_crc = rom_crc32c((const uint8_t *)&fw_words, 4);

    /*
     * Mask CPU IRQs before writing the command frame so the ISR cannot
     * fire between the explicit rom_isr_mailbox() call and the image write.
     * This prevents the ISR from consuming image words from the FIFO.
     */
    (void)rom_picorv32_maskirq(0xFFFFFFFFu);

    /* Write command frame */
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    if (!tb_sep_mbox_write(fw_words, 5000)) TEST_FAIL("fw_words write failed");
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(payload_crc, 5000)) TEST_FAIL("payload CRC write failed");

    /* Explicitly drain the command frame from FIFO into rom_rx_msgbuf. */
    test_delay(100);
    rom_isr_mailbox();

    /*
     * Write the image frame with a WRONG CRC.
     * Image frame: [14 image words][sep|WRONG_CRC]   (15 words, fits in FIFO).
     * Correct CRC XOR'd with 0xDEADBEEF to corrupt it.
     */
    for (uint32_t i = 0; i < MUTABLE_FW_BLOB_SMALL_WORDS; i++) {
        if (!tb_sep_mbox_write(mutable_fw_blob_small[i], 5000))
            TEST_FAIL("image word %u write failed", (unsigned)i);
    }
    uint32_t correct_crc =
        rom_crc32c((const uint8_t *)mutable_fw_blob_small, MUTABLE_FW_BLOB_SMALL_WORDS * 4u);
    uint32_t bad_crc = correct_crc ^ 0xDEADBEEFu;

    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("image separator write failed");
    if (!tb_sep_mbox_write(bad_crc, 5000)) TEST_FAIL("bad CRC write failed");

    /*
     * Dispatch.  The handler reads 14 image words, reads the bad CRC,
     * detects the mismatch, and calls rom_trigger_unrecoverable(ROM_KM_UFAULT_FW_CRC).
     * The CPU halts; this call never returns.
     */
    rom_msg_rx_process();

    TEST_FAIL("CMD_SRAM_LOAD_EXEC bad-CRC should have triggered unrecoverable fault");
    return 0;
}
