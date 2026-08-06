/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_abr_sk.c
 * @brief Adams Bridge ML-KEM shared-key capture + ABR seed transfer tests.
 *
 * Boots the KM firmware (production ISR) and exercises:
 *   1. CMD_ABR_SK_TRANSFER when no key is ready → FAILURE
 *   2. Load ABR shared key via TB → IRQ fires → g_abr_sk_notify_pending set
 *      → send RESP_ABR_SHARED_KEY_READY → verify it appears in outbound FIFO
 *   3. CMD_ABR_SK_TRANSFER(dest_valid=ML-DSA seed) → SUCCESS + handle returned
 *      → KEY_VALID cleared after capture
 *   4. CMD_KEY_GENERATE with ABR seed dest_valid bits (bits 4-7) → SUCCESS
 *   5. CMD_KEY_TRANSFER to ABR ML-DSA seed (bit 4) → SUCCESS
 *   6. CMD_ENGINE_SHRED ABR seeds (bits 4-7) → SUCCESS
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_abr_sk
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_msg_tx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_sideload.h"
#include "key_manager_fw.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/*===========================================================================
 * Helpers
 *===========================================================================*/

static uint8_t cmd_seq;

static void send_cmd_with_payload(uint8_t cmd_id, const uint32_t *payload, uint8_t payload_len) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");

    for (uint8_t i = 0; i < payload_len; i++) {
        if (!tb_sep_mbox_write(payload[i], 5000)) TEST_FAIL("payload write %u failed", (unsigned)i);
    }

    uint32_t crc = rom_crc32c((const uint8_t *)payload, payload_len * 4);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");
}

static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

/**
 * Read a RESP_CMD response from the outbound mailbox FIFO.
 * Fills *seq_echo, *cmd_echo, *rc, *arg.
 */
static void read_resp_cmd(rom_km_msg_header_t *rhdr, uint32_t *seq_echo, uint32_t *cmd_echo,
                          int8_t *rc, uint32_t *arg) {
    uint32_t payload_words[4] = {0};
    uint32_t word;
    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read response header");
    rhdr->raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ(rhdr->header_crc8, exp_crc, "resp header CRC");
    TEST_ASSERT_EQ(rhdr->id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    if (!tb_sep_mbox_read(seq_echo, 5000)) TEST_FAIL("Failed to read seq echo");
    payload_words[0] = *seq_echo;
    if (!tb_sep_mbox_read(cmd_echo, 5000)) TEST_FAIL("Failed to read cmd echo");
    payload_words[1] = *cmd_echo;

    uint32_t rc_word;
    if (!tb_sep_mbox_read(&rc_word, 5000)) TEST_FAIL("Failed to read return code");
    *rc = (int8_t)(rc_word & 0xFF);
    payload_words[2] = rc_word;

    if (rhdr->payload_len >= 4u) {
        if (!tb_sep_mbox_read(arg, 5000)) TEST_FAIL("Failed to read return arg");
        payload_words[3] = *arg;
    } else {
        *arg = 0;
    }

    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("Failed to read payload CRC");
    TEST_ASSERT(rhdr->payload_len == 3u || rhdr->payload_len == 4u, "resp payload_len=%u",
                (unsigned)rhdr->payload_len);
    TEST_ASSERT_EQ(crc_word,
                   rom_crc32c((const uint8_t *)payload_words, (uint32_t)rhdr->payload_len * 4u),
                   "resp payload CRC");
}

/**
 * Read a zero-payload unsolicited frame (e.g. RESP_ABR_SHARED_KEY_READY).
 * Verifies the header ID matches @p expected_id and the CRC is correct.
 */
static void read_unsolicited_frame(uint8_t expected_id) {
    uint32_t word;
    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read unsolicited frame header");

    rom_km_msg_header_t hdr;
    hdr.raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ(hdr.header_crc8, exp_crc, "unsolicited frame header CRC");
    TEST_ASSERT_EQ(hdr.id, (uint32_t)expected_id, "unsolicited frame ID");
    TEST_ASSERT_EQ(hdr.payload_len, 0u, "unsolicited frame has no payload");

    /* No payload CRC for zero-payload frames. */
}

/** Load 8 key words and set KEY_VALID via the testbench. */
static void tb_load_shared_key(uint32_t base_pattern) {
    uint8_t wi;
    for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
        if (!tb_drbg_set_next_value(base_pattern | wi, 1000))
            TEST_FAIL("tb_drbg_set_next_value failed for word %u", (unsigned)wi);
        if (!tb_abr_sk_load_word(wi, 1000))
            TEST_FAIL("tb_abr_sk_load_word(%u) failed", (unsigned)wi);
    }
    if (!tb_abr_sk_assert_valid(1000)) TEST_FAIL("tb_abr_sk_assert_valid failed");
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(3000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xABBEu, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    /* Boot the firmware: DRBG/PRNG init, KPV init, mailbox setup, ABR IRQ armed. */
    rom_boot_init();

    /* Discard RESP_KM_READY — the first word on the outbound FIFO after boot. */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY after boot");
        rom_km_msg_header_t rdy;
        rdy.raw = ready;
        TEST_ASSERT_EQ(rdy.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }

    cmd_seq = 0;

    /* =============================================================
     * Test 1: CMD_ABR_SK_TRANSFER when no key is available → FAILURE
     * ============================================================= */
    TEST_SUBTEST_START("CMD_ABR_SK_TRANSFER with no key ready → FAILURE");
    {
        /* ABR IRQ is armed but no key has been loaded yet, so KEY_VALID = 0. */
        uint32_t payload[1] = {(rom_km_dest_bits_t){.abr_mldsa_seed = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_ABR_SK_TRANSFER, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "no-key seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ABR_SK_TRANSFER, "no-key cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "no key → FAILURE");
        TEST_LOG("  Correctly rejected when KEY_VALID = 0");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* =============================================================
     * Test 2: Load ABR key → IRQ fires → g_abr_sk_notify_pending set
     *         → send RESP_ABR_SHARED_KEY_READY → verify in outbound FIFO
     * ============================================================= */
    TEST_SUBTEST_START("Shared-key IRQ → RESP_ABR_SHARED_KEY_READY sent");
    {
        /* TB loads key and sets KEY_VALID, which also hwsets the sticky
         * IRQ_STATUS bit. The production ISR (bit 5) fires, clears IRQ_STATUS
         * (W1C) to acknowledge, and sets g_abr_sk_notify_pending during the
         * busy-wait loop or shortly after. */
        tb_load_shared_key(0xCAFE0000u);

        /* Wait for the ISR to set the notify flag. */
        {
            uint32_t t = 500000u;
            while (g_abr_sk_notify_pending == 0u && t--) __asm__ volatile("nop");
            if (g_abr_sk_notify_pending == 0u)
                TEST_FAIL("g_abr_sk_notify_pending not set after loading shared key");
        }

        /* Simulate what rom_main_step() does: sample+clear flag, send notification. */
        g_abr_sk_notify_pending = 0u;
        rom_msg_tx_send(ROM_KM_RESP_ABR_SHARED_KEY_READY, NULL, 0);

        /* Drain TX buffer to outbound FIFO so TB can read it. */
        rom_isr_mailbox();
        test_delay(200);
        rom_isr_mailbox();

        /* Read and verify the unsolicited frame. */
        read_unsolicited_frame(ROM_KM_RESP_ABR_SHARED_KEY_READY);

        TEST_LOG("  RESP_ABR_SHARED_KEY_READY frame received; KEY_VALID still set");

        /* Verify KEY_VALID is still set (key not consumed by ISR). */
        if (!ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid)
            TEST_FAIL("KEY_VALID was cleared by ISR (should stay set for CMD_ABR_SK_TRANSFER)");
    }
    TEST_SUBTEST_PASS();

    /* =============================================================
     * Test 3: CMD_ABR_SK_TRANSFER(dest_valid=ML-DSA seed) → SUCCESS
     *         Key consumed, KEY_VALID cleared, handle returned.
     * ============================================================= */
    TEST_SUBTEST_START("CMD_ABR_SK_TRANSFER → SUCCESS + handle");
    uint8_t sk_handle;
    {
        rom_km_dest_bits_t dest = {.abr_mldsa_seed = 1};
        uint32_t payload[1] = {dest.raw};
        send_cmd_with_payload(ROM_KM_CMD_ABR_SK_TRANSFER, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "transfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ABR_SK_TRANSFER, "transfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "transfer success");
        rom_km_handle_ret_t ret = {.raw = arg};
        sk_handle = (uint8_t)ret.key_handle;
        TEST_ASSERT_NE(sk_handle, (uint32_t)ROM_KM_KEY_HANDLE_NULL, "handle non-null");
        TEST_LOG("  Captured shared key into KPV; handle=%u", (unsigned)sk_handle);

        /* Verify KEY_VALID is cleared after capture. */
        if (ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid)
            TEST_FAIL("KEY_VALID not cleared after CMD_ABR_SK_TRANSFER");
        TEST_LOG("  KEY_VALID cleared after capture");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* =============================================================
     * Test 4: CMD_KEY_GENERATE with ABR seed dest_valid (bit 5 = ML-KEM seed D)
     * ============================================================= */
    TEST_SUBTEST_START("CMD_KEY_GENERATE dest_valid=ABR_ML-KEM_SEED_D (bit 5)");
    uint8_t gen_handle;
    {
        rom_km_dest_bits_t dest = {.abr_mlkem_seed_d = 1};
        uint32_t payload[2] = {7u, (uint32_t)dest.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "keygen seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_GENERATE, "keygen cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen success");
        rom_km_key_generate_ret_t ret = {.raw = arg};
        gen_handle = (uint8_t)ret.key_handle;
        TEST_ASSERT_NE(gen_handle, (uint32_t)ROM_KM_KEY_HANDLE_NULL, "gen handle non-null");
        TEST_ASSERT_EQ(ret.dest_valid, (uint32_t)dest.raw, "keygen echoes dest_valid");
        TEST_LOG("  Generated key with ABR ML-KEM seed D dest_valid; handle=%u",
                 (unsigned)gen_handle);
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* =============================================================
     * Test 5: CMD_KEY_TRANSFER to ABR ML-KEM seed D using the handle from Test 4
     * ============================================================= */
    TEST_SUBTEST_START("CMD_KEY_TRANSFER → ABR ML-KEM seed D (bit 5)");
    {
        rom_km_dest_bits_t dest = {.abr_mlkem_seed_d = 1};
        uint32_t payload[2] = {(uint32_t)gen_handle, (uint32_t)dest.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "xfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "xfer ABR ML-KEM seed D success");
        TEST_LOG("  Transferred key to ABR ML-KEM seed D engine");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* =============================================================
     * Test 6: CMD_ENGINE_SHRED all four ABR seed engines → SUCCESS
     * ============================================================= */
    TEST_SUBTEST_START("CMD_ENGINE_SHRED all ABR seeds (bits 4-7)");
    {
        rom_km_dest_bits_t all_abr = {
            .abr_mldsa_seed = 1, .abr_mlkem_seed_d = 1, .abr_mlkem_seed_z = 1, .abr_mlkem_msg = 1};
        uint32_t payload[1] = {all_abr.raw};
        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "shred seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "shred cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "shred all ABR success");
        rom_km_engine_shred_ret_t shred_ret = {.raw = arg};
        TEST_ASSERT_EQ(shred_ret.dest_engine, (uint32_t)all_abr.raw, "shred echoes dest");
        TEST_LOG("  All four ABR seed engines shredded");
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
