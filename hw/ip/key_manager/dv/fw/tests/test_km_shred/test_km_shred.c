/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_shred.c
 * @brief Engine shred test
 *
 * Boots the KM firmware and exercises the CMD_ENGINE_SHRED command:
 *   1. Generate key, transfer to AES, then shred AES → success
 *   2. Shred with dest = 0 → INVALID_ARG
 *   3. Shred with invalid bits (0x100) → INVALID_ARG (bit 8 is above the 8-bit mask)
 *   4. Multi-engine shred: AES|KMAC → success
 *   5. Shred ABR ML-DSA seed (bit 4) → success
 *   6. Shred all four ABR seeds at once → success
 *
 * CMD_ENGINE_SHRED payload[0] bits [7:0] = dest engine bitmask.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_shred
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"

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

    if (rhdr->payload_len >= 4) {
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

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0x5D57u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
        rom_km_msg_header_t rdy;
        rdy.raw = ready;
        TEST_ASSERT_EQ(rdy.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }

    cmd_seq = 0;

    /*=================================================================
     * Setup: Generate key and transfer to AES so there is key
     * material in the engine registers before shredding.
     *=================================================================*/
    TEST_SUBTEST_START("Setup: generate key and transfer to AES");
    {
        uint32_t gen_pl[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, gen_pl, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);
        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "setup keygen seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_GENERATE, "setup keygen cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen success");

        rom_km_key_generate_ret_t gen_ret = {.raw = arg};
        uint8_t handle = gen_ret.key_handle;
        TEST_ASSERT_NE(handle, 0u, "handle non-zero");
        cmd_seq++;

        /* Transfer to AES */
        uint32_t xfer_pl[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, xfer_pl, 2);
        process_and_drain();

        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);
        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "setup xfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "setup xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "xfer AES success");
        TEST_LOG("  key loaded into AES engine");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 1: Shred AES engine → success
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED AES");
    {
        uint32_t payload[1] = {(rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "shred AES seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "shred cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "shred AES success");
        rom_km_engine_shred_ret_t shred_ret = {.raw = arg};
        TEST_ASSERT_EQ(shred_ret.dest_engine, (uint32_t)(rom_km_dest_bits_t){.aes = 1}.raw,
                       "shred echoes dest");
        TEST_LOG("  AES engine shredded");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 2: Shred with dest = 0 → INVALID_ARG
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED dest=0 → INVALID_ARG");
    {
        uint32_t payload[1] = {0u};

        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "shred zero seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "shred zero cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "dest=0 → INVALID_ARG");
        TEST_LOG("  dest=0 correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 3: Shred with invalid bits (0x100) → INVALID_ARG
     *
     * Valid dest bits are [7:0] (classic engines plus the 4 ABR seeds).
     * Bit 8 (0x100) is above the 8-bit mask and must be rejected.
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED invalid bits (above mask) → INVALID_ARG");
    {
        uint32_t payload[1] = {0x100u};

        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "shred invalid seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "shred invalid cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG,
                       "dest=0x100 (above 8-bit mask) → INVALID_ARG");
        TEST_LOG("  dest=0x100 correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 4: Multi-engine shred: AES|KMAC → success
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED AES|KMAC");
    {
        uint32_t payload[1] = {(rom_km_dest_bits_t){.aes = 1, .kmac_sha3 = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "multi-shred seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "multi-shred cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "multi-engine shred success");
        rom_km_engine_shred_ret_t shred_ret = {.raw = arg};
        uint32_t expect_dest = (rom_km_dest_bits_t){.aes = 1, .kmac_sha3 = 1}.raw;
        TEST_ASSERT_EQ(shred_ret.dest_engine, expect_dest, "multi-shred echoes dest");
        TEST_LOG("  AES|KMAC shredded");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 5: ABR-seed shred: ML-DSA seed (bit 4) → success
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED ABR ML-DSA seed");
    {
        uint32_t payload[1] = {(rom_km_dest_bits_t){.abr_mldsa_seed = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "abr-shred mldsa seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "abr-shred mldsa cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "abr-shred mldsa success");
        TEST_LOG("  ABR ML-DSA seed shredded");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 6: ABR-seed shred: all four ABR seeds simultaneously → success
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ENGINE_SHRED all four ABR seeds");
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

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "abr-shred all seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ENGINE_SHRED, "abr-shred all cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "abr-shred all success");
        rom_km_engine_shred_ret_t shred_ret = {.raw = arg};
        TEST_ASSERT_EQ(shred_ret.dest_engine, (uint32_t)all_abr.raw, "abr-shred all echoes dest");
        TEST_LOG("  All four ABR seeds shredded");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
