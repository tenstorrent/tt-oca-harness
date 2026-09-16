/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_boot.c
 * @brief Boot initialization integration test
 *
 * Calls rom_boot_init() and verifies:
 *  1. SRAM scrambler is enabled and locked
 *  2. KPV scrambler is enabled and locked
 *  3. KMCSR fault IRQs are all enabled
 *  4. Crypto engine key_valid bits are cleared after shred
 *  5. Mailbox IRQ enable mask is correct
 *  6. RESP_KM_READY was sent to the outgoing mailbox with correct format
 *
 * Double-boot pattern: on first entry the SRAM scrambler is off, so
 * rom_boot_init() writes the scrambler key, enables + locks the scrambler,
 * and restarts the CPU (jump to address 0).  crt0.s re-clears BSS and
 * calls main() again.  On the second entry the scrambler is already
 * enabled, so boot proceeds through KPV init, shredding, mailbox setup,
 * and RESP_KM_READY.  TEST_INIT() and the DRBG seed are re-applied on
 * each entry which is safe — TB protocol registers persist across the
 * soft restart and are simply re-initialized.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_boot
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_crc.h"

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(2000000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xB007u, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /*
     * Run the full boot sequence.
     *
     * First pass: SRAM scrambler disabled → boot_init writes scrambler
     * key, enables + locks it, jumps to 0x0 (restart).
     * Second pass: SRAM scrambler enabled → KPV scrambler init, shred
     * all KPV slots + crypto engine keys, mailbox setup, RESP_KM_READY.
     */
    rom_boot_init();

    /* --- Subtest 1: SRAM scrambler enabled and locked --- */
    TEST_SUBTEST_START("SRAM scrambler enabled and locked");
    {
        km_csr__scrambler_ctrl_reg_t scram_ctrl;
        scram_ctrl.w = test_read32(KEY_MANAGER_KMCSR_SCRAMBLER_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(scram_ctrl.f.enable, 1u, "SRAM scrambler enable");
        TEST_ASSERT_EQ(scram_ctrl.f.lock, 1u, "SRAM scrambler lock");
    }
    TEST_SUBTEST_PASS();

    /* --- Subtest 2: KPV scrambler enabled and locked --- */
    TEST_SUBTEST_START("KPV scrambler enabled and locked");
    {
        km_kpv__kpv_scrambler_ctrl_reg_t kpv_ctrl;
        kpv_ctrl.w = test_read32(KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(kpv_ctrl.f.enable, 1u, "KPV scrambler enable");
        TEST_ASSERT_EQ(kpv_ctrl.f.lock, 1u, "KPV scrambler lock");
    }
    TEST_SUBTEST_PASS();

    /* --- Subtest 3: KMCSR fault IRQs enabled --- */
    TEST_SUBTEST_START("KMCSR fault IRQs enabled");
    {
        km_csr__irq_enable_reg_t irq_en;
        irq_en.w = test_read32(KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR);
        TEST_ASSERT_EQ(irq_en.f.rom_parity_en, 1u, "rom_parity_en");
        TEST_ASSERT_EQ(irq_en.f.sram_parity_en, 1u, "sram_parity_en");
        TEST_ASSERT_EQ(irq_en.f.rom_write_en, 1u, "rom_write_en");
        TEST_ASSERT_EQ(irq_en.f.sram_write_lock_en, 1u, "sram_write_lock_en");
        TEST_ASSERT_EQ(irq_en.f.axi_slverr_en, 1u, "axi_slverr_en");
        TEST_ASSERT_EQ(irq_en.f.axi_decerr_en, 1u, "axi_decerr_en");
        TEST_ASSERT_EQ(irq_en.f.drbg_err_en, 1u, "drbg_err_en");
        TEST_ASSERT_EQ(irq_en.f.wipe_state_en, 1u, "wipe_state_en");
    }
    TEST_SUBTEST_PASS();

    /* --- Subtest 4: Crypto engine key_valid cleared after shred --- */
    TEST_SUBTEST_START("Crypto engine key_valid cleared after shred");
    {
        hmac_wrapper_key__key_ctrl_reg_t hmac_ctrl;
        hmac_ctrl.w = test_read32(KEY_MANAGER_HMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(hmac_ctrl.f.key_valid, 0u, "HMAC key_valid");

        kmac_wrapper_key__key_ctrl_reg_t kmac_ctrl;
        kmac_ctrl.w = test_read32(KEY_MANAGER_KMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(kmac_ctrl.f.key_valid, 0u, "KMAC key_valid");

        aes_wrapper_key__key_ctrl_reg_t aes_ctrl;
        aes_ctrl.w = test_read32(KEY_MANAGER_AES_WRAPPER_KEY_KEY_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(aes_ctrl.f.key_valid, 0u, "AES key_valid");

        otbn_wrapper_key__key_ctrl_reg_t otbn_ctrl;
        otbn_ctrl.w = test_read32(KEY_MANAGER_OTBN_WRAPPER_KEY_KEY_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(otbn_ctrl.f.key_valid, 0u, "OTBN key_valid");
    }
    TEST_SUBTEST_PASS();

    /* --- Subtest 5: Mailbox IRQ enables --- */
    TEST_SUBTEST_START("Mailbox IRQ enables");
    {
        km_mailbox_km__irq_enable_reg_t mbox_en;
        mbox_en.w = test_read32(KEY_MANAGER_MAILBOX_KM_KM_IRQ_ENABLE_BASE_ADDR);
        TEST_ASSERT_EQ(mbox_en.f.inbound_read_data_avail_en, 1u, "inbound_read_data_avail_en");
        TEST_ASSERT_EQ(mbox_en.f.outbound_write_space_avail_en, 0u,
                       "outbound_write_space_avail_en");
        TEST_ASSERT_EQ(mbox_en.f.outbound_overflow_en, 1u, "outbound_overflow_en");
        TEST_ASSERT_EQ(mbox_en.f.inbound_underflow_en, 1u, "inbound_underflow_en");
        TEST_ASSERT_EQ(mbox_en.f.flushed_by_sep_en, 1u, "flushed_by_sep_en");
    }
    TEST_SUBTEST_PASS();

    /* --- Subtest 6: RESP_KM_READY in outbound mailbox --- */
    TEST_SUBTEST_START("RESP_KM_READY in outbound mailbox");
    {
        uint32_t header_word;
        if (!tb_sep_mbox_read(&header_word, 5000)) {
            TEST_FAIL("No RESP_KM_READY in outbound mailbox");
        }

        rom_km_msg_header_t hdr;
        hdr.raw = header_word;

        TEST_LOG("  Header raw: 0x%08X", header_word);
        TEST_LOG("  id=0x%02X seq=%u len=%u crc=0x%02X", hdr.id, hdr.seq_num, hdr.payload_len,
                 hdr.header_crc8);

        TEST_ASSERT_EQ(hdr.id, (uint32_t)ROM_KM_RESP_KM_READY, "resp_id");
        TEST_ASSERT_EQ(hdr.seq_num, 0u, "seq_num");
        TEST_ASSERT_EQ(hdr.payload_len, 0u, "payload_len");

        /* Verify CRC-8/ROHC over the lower 24 bits of the header */
        uint8_t lower24[3];
        lower24[0] = (uint8_t)(header_word & 0xFFu);
        lower24[1] = (uint8_t)((header_word >> 8) & 0xFFu);
        lower24[2] = (uint8_t)((header_word >> 16) & 0xFFu);
        uint8_t expected_crc = rom_crc8_rohc(lower24, 3);
        TEST_ASSERT_EQ(hdr.header_crc8, expected_crc, "header CRC-8/ROHC");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
